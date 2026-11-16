"""Command line entry point."""

from __future__ import annotations

import argparse
import sys

from . import config, db


def cmd_init(args) -> int:
    db.init()
    print(f"Initialised {config.DB_PATH}")
    return 0


def cmd_backfill(args) -> int:
    from .sources import nflverse

    seasons = args.seasons or config.BACKFILL_SEASONS
    db.init()

    with db.session() as conn:
        n = nflverse.sync_games(conn, seasons, refresh=args.refresh)
    print(f"games            {n:>7} rows upserted")

    for label, fn in (
        ("pbp", nflverse.pbp),
        ("injuries", nflverse.injuries),
        ("officials", nflverse.officials),
        ("ftn_charting", nflverse.ftn_charting),
    ):
        df = fn(seasons, refresh=args.refresh)
        skipped = sorted(nflverse.UNAVAILABLE.get(label, set()))
        note = f"  (not published yet: {', '.join(map(str, skipped))})" if skipped else ""
        print(f"{label:<16} {df.height:>7} rows cached{note}")
    return 0


def cmd_refresh(args) -> int:
    """Pull the current season's data again, including final scores.

    Grading reads `games.home_score`, which only ever gets written by
    `sync_games`. Without this running before `grade`, finished games stay
    NULL in the database and nothing is ever scored -- predictions accumulate
    and the record sits at 0-0 all season.
    """
    from .sources import nflverse

    season = args.season or config.current_season()
    db.init()
    with db.session() as conn:
        n = nflverse.sync_games(conn, [season], refresh=True)
        played = conn.execute(
            "SELECT COUNT(*) n FROM games WHERE season = ? AND home_score IS NOT NULL",
            (season,),
        ).fetchone()["n"]

    print(f"games            {n:>7} rows upserted for {season}")
    print(f"with final score {played:>7}")

    # Injuries and play-by-play move week to week; refreshing them here keeps
    # the next prediction run from reading a stale cache.
    for label, fn in (("injuries", nflverse.injuries), ("pbp", nflverse.pbp)):
        df = fn([season], refresh=True)
        skipped = sorted(nflverse.UNAVAILABLE.get(label, set()))
        note = "  (not published yet)" if skipped else ""
        print(f"{label:<16} {df.height:>7} rows{note}")
    return 0


def cmd_status(args) -> int:
    db.init()
    with db.session() as conn:
        rows = conn.execute(
            "SELECT season, COUNT(*) n, SUM(home_score IS NULL) unplayed "
            "FROM games GROUP BY season ORDER BY season"
        ).fetchall()
        for r in rows:
            print(f"season {r['season']}  games {r['n']:>4}  unplayed {r['unplayed']:>4}")

        snaps = conn.execute("SELECT COUNT(*) n FROM line_snapshots").fetchone()["n"]
        preds = conn.execute("SELECT COUNT(*) n FROM predictions").fetchone()["n"]
        graded = conn.execute("SELECT COUNT(*) n FROM results").fetchone()["n"]
        print(f"line snapshots {snaps}   predictions {preds}   graded {graded}")
    return 0


def cmd_features(args) -> int:
    import json

    from .features.build import FeatureBuilder

    db.init()
    with db.session() as conn:
        row = conn.execute(
            "SELECT season FROM games WHERE game_id = ?", (args.game,)
        ).fetchone()
        if row is None:
            print(f"unknown game_id {args.game!r}", file=sys.stderr)
            return 1
        season = row["season"]
        builder = FeatureBuilder(sorted({season - 1, season}))
        pack = builder.build(conn, args.game)
        if args.store:
            fid = builder.store(conn, args.game, pack)
            print(f"stored features id={fid}", file=sys.stderr)

    if args.gaps_only:
        print(json.dumps(pack["data_gaps"], indent=2))
    else:
        print(json.dumps(pack, indent=2))
    return 0


def cmd_snapshot_lines(args) -> int:
    """Record the current nflverse line. No API key required."""
    from .sources import nflverse

    db.init()
    season = args.season or config.current_season()
    with db.session() as conn:
        out = nflverse.snapshot_lines(conn, [season])
    for k, v in out.items():
        print(f"{k:<14} {v}")
    if out.get("snapshots") == 0 and out.get("games"):
        print("(no line moved since the last snapshot)")
    return 0


def cmd_poll_odds(args) -> int:
    import os

    from .sources import nflverse, odds

    db.init()
    with db.session() as conn:
        if args.purge_unmatched:
            n = odds.purge_unmatched(conn)
            print(f"deleted {n} unmatched snapshot rows")
            return 0

        # Without a paid feed, fall back to snapshotting the nflverse line.
        # That still yields opening number, movement and CLV -- just from one
        # consensus source rather than thirty books.
        if not os.getenv("ODDS_API_KEY"):
            season = args.season or config.current_season()
            out = nflverse.snapshot_lines(conn, [season])
            print("no ODDS_API_KEY; snapshotting the free nflverse line instead")
            for k, v in out.items():
                print(f"{k:<14} {v}")
            return 0

        try:
            summary = odds.poll(conn, budget=args.budget, dry_run=args.dry_run)
        except odds.BudgetExceeded as e:
            print(f"skipped: {e}", file=sys.stderr)
            return 2

    sample = summary.pop("sample", [])
    for k, v in summary.items():
        if v is not None:
            print(f"{k:<28} {v}")
    if sample:
        print("\nsample rows:")
        for s in sample:
            matched = s["game_id"] or "unmatched (not a scheduled game)"
            print(
                f"  {s['matchup']:<12} {s['book']:<12} "
                f"spread_home {str(s['spread_home']):>6}  total {str(s['total']):>6}  {matched}"
            )
    if summary.get("dry_run"):
        print("\ndry run: nothing written to line_snapshots")
    return 0


def refresh_lines(conn, season: int) -> dict:
    """Snapshot the current nflverse line for every unplayed game. No cost."""
    from .sources import nflverse

    snap = nflverse.snapshot_lines(conn, [season])
    print(f"lines: {snap.get('snapshots', 0)} moved of {snap.get('games', 0)} upcoming")
    return snap


def predict_one(conn, builder, game_id: str, *, effort=None, label="manual",
                verbose=False, pack: dict | None = None) -> dict | None:
    """Build, predict, store and print one game. None when the call failed.

    BudgetExceeded propagates so a caller can stop the whole run.
    """
    from . import predict as predictor

    pack = pack or builder.build(conn, game_id)
    features_id = builder.store(conn, game_id, pack)
    try:
        result = predictor.predict(pack, conn, effort=effort, run_label=label)
    except predictor.BudgetExceeded:
        raise
    except Exception as e:
        print(f"{game_id}: FAILED {e}", file=sys.stderr)
        return None

    pid = predictor.store(conn, game_id, features_id, pack, result, run_label=label)
    # A fresh pick answers whatever flagged the old one, however it was run.
    conn.execute("DELETE FROM recheck_flags WHERE game_id = ?", (game_id,))
    # Commit per game rather than per slate. A sixteen-game run takes minutes,
    # and holding the write lock for all of it would block the line poller that
    # fires on its own schedule.
    conn.commit()
    print(
        f"{game_id:<20} {result['pick_type']:<7} {result['pick_side']:<6} "
        f"conf {result['confidence']:>3}  "
        f"proj {result['projected_margin']:+.1f}/{result['projected_total']:.1f}  "
        f"[#{pid}]"
    )
    if verbose:
        print(f"  {result['paragraph']}\n")
    return result


def blind_context(conn, season: int, packs) -> tuple[dict, dict]:
    """The computed baseline and the factor corrections a blind pick needs.

    The baseline is told who is expected to start each game, from the packs
    themselves, so a quarterback ruled out this week moves it this week.
    """
    from . import calibration, shadow

    base = shadow.baselines(season, starters=shadow.expected_starters(packs))
    # Learned from every graded blind pick so far; unplayed games have no
    # score, so nothing about the games being predicted can leak in.
    return base, calibration.current(conn)


def blind_one(conn, builder, game_id: str, base: dict, calib: dict, *,
              pack: dict | None = None, effort=None, usage_label: str = "blind",
              verbose: bool = False) -> dict | None:
    """Build, predict blind, store as the official pick and print. None on failure.

    `usage_label` is what the spend ledger records (a scheduled recheck counts
    against its own weekly cap). The pick itself is always stored as `blind`,
    which is what the corrections and the record read.
    BudgetExceeded propagates so a caller can stop the whole run.
    """
    from . import predict as predictor
    from . import shadow

    pack = pack or builder.build(conn, game_id)
    features_id = builder.store(conn, game_id, pack)
    try:
        out = shadow.predict(pack, conn, base.get(game_id), effort=effort,
                             run_label=usage_label)
    except predictor.BudgetExceeded:
        raise
    except Exception as e:  # noqa: BLE001
        print(f"{game_id}: FAILED {e}", file=sys.stderr)
        return None
    calc = shadow.assemble(pack, out, base.get(game_id), calib)
    result = shadow.to_prediction(pack, out, calc)
    pid = predictor.store(conn, game_id, features_id, pack, result,
                          run_label="blind", conviction=calc["tier"])
    # A fresh pick answers whatever flagged the old one.
    conn.execute("DELETE FROM recheck_flags WHERE game_id = ?", (game_id,))
    conn.commit()
    _print_blind(game_id, calc, f"#{pid}")
    if verbose:
        print(f"  {out['headline']}\n  {out['paragraph']}\n")
    return out


def _print_blind(game_id: str, calc: dict, ref: str) -> None:
    print(
        f"{game_id:<20} {calc['winner'] or 'tie':<4} by {abs(calc['projected_margin']):>4.1f} "
        f"({calc['home_win_prob']:.0%} home)  elo {calc['baseline_margin']:+.1f}  "
        f"line {calc['line_home']}  -> {calc['pick_side']} {calc['tier']} "
        f"edge {calc['edge']}  [{ref}]"
    )


def cmd_recheck(args) -> int:
    from . import predict as predictor
    from . import recheck
    from .features.build import FeatureBuilder

    db.init()
    season = args.season or config.current_season()
    cap = config.RECHECK_WEEKLY_USD if args.cap is None else args.cap
    with db.session() as conn:
        refresh_lines(conn, season)
        builder = FeatureBuilder(sorted({season - 1, season}))
        flagged = recheck.detect(conn, builder, season, args.week)
        recheck.store_flags(conn, season, args.week, flagged)
        conn.commit()

        if not flagged:
            print("no changes: every unplayed pick still matches its inputs")
            return 0
        for f in flagged:
            if recheck.worth_rerun(f["reasons"]):
                tag = "RERUN"
            elif any(r.startswith(recheck.UNCONFIRMED) for r in f["reasons"]):
                tag = "quarterback unconfirmed, no rerun"
            else:
                tag = "injury only, no rerun"
            print(f"{f['game_id']}  [{tag}]")
            for r in f["reasons"]:
                print(f"   - {r}")
        worth = [f for f in flagged if recheck.worth_rerun(f["reasons"])]

        if not args.run:
            print(f"\n{len(flagged)} flagged, {len(worth)} worth a rerun; not rerun (no --run)")
            return 0

        est = recheck.call_estimate(conn)
        spent = recheck.week_spend(conn, season, args.week)
        if args.allow is not None:
            cap = spent + args.allow
        print(f"\nweek {args.week} recheck spend ${spent:.2f} of ${cap:.2f} cap, ~${est:.2f}/call")
        # Reruns go through the blind predictor, the one that makes the
        # official picks. Until 2026-11-16 this called the old line-anchored
        # predictor, so a rerun would have swapped predictors mid-week.
        context = None
        for f in worth:
            if spent + est > cap:
                print(f"{f['game_id']}: left flagged, cap reached")
                continue
            if context is None:
                context = blind_context(conn, season, [w["pack"] for w in worth])
            try:
                blind_one(conn, builder, f["game_id"], *context,
                          pack=f["pack"], usage_label="recheck")
            except predictor.BudgetExceeded as e:
                print(f"stopping: {e}", file=sys.stderr)
                break
            spent = recheck.week_spend(conn, season, args.week)
        left = conn.execute(
            "SELECT COUNT(*) FROM recheck_flags f JOIN games g ON g.game_id = f.game_id "
            "WHERE g.season = ? AND g.week = ?", (season, args.week),
        ).fetchone()[0]
        print(f"week {args.week} recheck spend now ${spent:.2f}; {left} still flagged")
    return 0


def cmd_predict(args) -> int:
    import json

    from . import predict as predictor
    from .features.build import FeatureBuilder, slate_game_ids, split_played

    db.init()
    with db.session() as conn:
        if args.game:
            row = conn.execute(
                "SELECT season FROM games WHERE game_id = ?", (args.game,)
            ).fetchone()
            if row is None:
                print(f"unknown game_id {args.game!r}", file=sys.stderr)
                return 1
            season = row["season"]
        else:
            season = args.season or config.current_season()

        # FIRST, before anything reads a line: snapshot the current one. The
        # market block reads line_snapshots, not games.spread_line, and
        # `--only-moved` picks its games by line movement -- so both need the
        # fresh number. A manual run that skipped this priced ATL/GB off a
        # week-old 6.5 while the real line was 4.5. Free: nflverse only, and
        # it writes nothing when no line has moved.
        if args.label != "backtest":
            refresh_lines(conn, season)

        if args.game:
            game_ids = [args.game]
        else:
            if args.only_moved:
                from .features.market import games_needing_repredict

                game_ids = games_needing_repredict(conn, season, args.week)
                if not game_ids:
                    print("nothing to do: no game crossed a key number since the last run")
                    return 0
            else:
                game_ids = slate_game_ids(conn, season, args.week)
            if not game_ids:
                print(f"no games for {season} week {args.week}", file=sys.stderr)
                return 1

        # Backtests predict finished games on purpose and never supersede a
        # live pick. Everything else must not touch a game with a result.
        if args.label != "backtest":
            game_ids, played = split_played(conn, game_ids)
            for g in played:
                print(f"skip {g}: already played; a new pick would replace its graded result")
            if not game_ids:
                print("nothing to do: every selected game has already been played")
                return 0

        builder = FeatureBuilder(sorted({season - 1, season}))
        spent = 0.0

        for game_id in game_ids:
            if args.dry_run:
                print(f"===== {game_id} =====")
                print(predictor.build_prompt(builder.build(conn, game_id)))
                continue
            try:
                result = predict_one(
                    conn, builder, game_id, effort=args.effort, label=args.label,
                    verbose=args.verbose,
                )
            except predictor.BudgetExceeded as e:
                print(f"stopping: {e}", file=sys.stderr)
                break
            if result:
                spent += result.get("_cost_usd", 0.0)

        if not args.dry_run:
            mtd = predictor.month_spend(conn)
            print(
                f"\nthis run ${spent:.3f} · month to date ${mtd:.2f} "
                f"of ${config.MONTHLY_BUDGET_USD:.2f}"
            )
    return 0


def cmd_confidence(args) -> int:
    from . import evidence

    db.init()
    with db.session() as conn:
        a = evidence.assess(conn, season=args.season)

    print(f"VERDICT   {a['verdict'].upper()}  ({a['score']}/100)")
    print(f"record    {a['record']}  ({a['plays_decided']} decided plays)")
    if a["win_pct"] is not None:
        lo, hi = a["win_pct_95_interval"]
        print(
            f"win rate  {a['win_pct']:.1%}   break-even {a['breakeven_pct']:.2%}   "
            f"95% CI {lo:.1%}-{hi:.1%}"
        )
        print(f"units     {a['units']:+.2f}   p vs break-even {a['p_value_vs_breakeven']}")
    if a["clv"].get("mean") is not None:
        print(f"avg CLV   {a['clv']['mean']:+.2f} pts   positive on "
              f"{a['clv']['positive_rate']:.0%} of plays")

    print("\nwhy:")
    for r in a["reasons"]:
        print(f"  - {r}")
    return 0


def cmd_spend(args) -> int:
    from . import predict as predictor

    db.init()
    with db.session() as conn:
        rows = conn.execute(
            "SELECT strftime('%Y-%m', called_at) month, model, COUNT(*) calls, "
            "SUM(input_tokens) inp, SUM(output_tokens) outp, SUM(cost_usd) cost "
            "FROM api_usage GROUP BY month, model ORDER BY month DESC, cost DESC"
        ).fetchall()

        if not rows:
            print("no model calls recorded yet")
        else:
            print(f"{'month':<9}{'model':<20}{'calls':>6}{'in':>10}{'out':>10}{'cost':>10}")
            for r in rows:
                print(
                    f"{r['month']:<9}{r['model']:<20}{r['calls']:>6}"
                    f"{r['inp']:>10,}{r['outp']:>10,}{'$' + format(r['cost'], '.2f'):>10}"
                )

        mtd = predictor.month_spend(conn)
        ceiling = config.MONTHLY_BUDGET_USD
        pct = (mtd / ceiling * 100) if ceiling else 0
        print(f"\nmonth to date ${mtd:.2f} of ${ceiling:.2f} ceiling ({pct:.0f}%)")
    return 0


def cmd_grade(args) -> int:
    from . import track

    db.init()
    with db.session() as conn:
        n = track.grade(conn, regrade=args.regrade)
        print(f"graded {n} predictions")
        rec = track.record(conn, season=args.season)
        if not rec["overall"].get("plays"):
            print("nothing graded yet")
            return 0
        for label, block in (("OVERALL", rec["overall"]), *rec["by_market"].items()):
            print(f"\n{str(label).upper()}")
            for k, v in block.items():
                print(f"  {k:<18} {v}")
        if rec["by_confidence"]:
            print("\nBY CONFIDENCE BUCKET")
            for name, block in rec["by_confidence"].items():
                print(
                    f"  {name:<8} {block['record']:<10} "
                    f"units {block['units']:+.2f}  clv {block['avg_clv']}"
                )
    return 0


def cmd_postmortem(args) -> int:
    from . import postmortem

    db.init()
    season = args.season or config.current_season()
    with db.session() as conn:
        def report_one(row, miss, narrative):
            dog = "dog" if miss.get("underdog") else "fav"
            print(
                f"\nW{row['week']} {row['away_team']} at {row['home_team']} "
                f"({row['home_team']} {row['home_score']}-{row['away_score']})"
            )
            print(
                f"  pick {miss['pick_side']} {miss['line']:+g} ({dog}) "
                f"conf {miss.get('confidence')} {miss.get('conviction')}"
            )
            if miss.get("points_short") is not None:
                print(
                    f"  lost by {miss['points_short']:g} against the number "
                    f"[{miss['severity']}], projection off by "
                    f"{miss.get('projection_error')}"
                )
            if miss.get("projected_edge") is not None:
                print(f"  edge it thought it had: {miss['projected_edge']:+g}")
            heaviest = miss["factors"].get("heaviest_wrong")
            if heaviest:
                print(f"  heaviest wrong factor: {heaviest['factor']} ({heaviest['weight']})")
            if narrative:
                print(f"  VERDICT {narrative['verdict']}")
                print(f"  LESSON  {narrative['lesson']}")

        out = postmortem.generate(
            conn,
            season=season,
            week=args.week,
            regenerate=args.regenerate,
            with_model=not args.no_model,
            limit=args.limit,
            on_event=report_one,
        )

    print()
    for k in ("losses", "computed", "explained", "failed", "cost_usd"):
        print(f"{k:<10} {out[k]}")
    for err in out["errors"]:
        print(f"error: {err}", file=sys.stderr)
    return 0


def cmd_shadow(args) -> int:
    """The blind predictor. `--official` stores the pick of record; otherwise a shadow."""
    from . import shadow
    from . import predict as predictor
    from .features.build import FeatureBuilder, slate_game_ids, split_played

    db.init()
    season = args.season or config.current_season()
    with db.session() as conn:
        refresh_lines(conn, season)
        game_ids = [args.game] if args.game else slate_game_ids(conn, season, args.week)
        game_ids, played = split_played(conn, game_ids)
        for g in played:
            print(f"skip {g}: already played")
        if not game_ids:
            print("nothing to do")
            return 0

        builder = FeatureBuilder(sorted({season - 1, season}))
        packs = {g: builder.build(conn, g) for g in game_ids}
        base, calib = blind_context(conn, season, packs.values())
        print(f"factor corrections from {calib['n_games']} graded games: "
              + ", ".join(f"{k} x{m:g}" for k, m in calib["multipliers"].items() if m != 1.0)
              if calib["n_games"] else "factor corrections: none yet")
        spent = 0.0
        for game_id in game_ids:
            pack = packs[game_id]
            if args.dry_run:
                prompt = shadow.build_prompt(pack, base.get(game_id))
                print(f"===== {game_id} ({len(prompt):,} chars) =====")
                print(prompt if args.verbose else prompt[:4000] + "\n...")
                continue
            try:
                if args.official:
                    # The official pick for this game: same table, record and
                    # site as the live predictor, with the blind predictor's tier.
                    out = blind_one(conn, builder, game_id, base, calib, pack=pack,
                                    effort=args.effort, verbose=args.verbose)
                    if out is None:
                        continue
                else:
                    features_id = builder.store(conn, game_id, pack)
                    try:
                        out = shadow.predict(pack, conn, base.get(game_id),
                                             effort=args.effort, run_label="shadow")
                    except predictor.BudgetExceeded:
                        raise
                    except Exception as e:  # noqa: BLE001
                        print(f"{game_id}: FAILED {e}", file=sys.stderr)
                        continue
                    calc = shadow.assemble(pack, out, base.get(game_id), calib)
                    sid = shadow.store(conn, game_id, features_id, out, calc)
                    conn.commit()
                    _print_blind(game_id, calc, f"s#{sid}")
                    if args.verbose:
                        print(f"  {out['headline']}\n  {out['paragraph']}\n")
            except predictor.BudgetExceeded as e:
                print(f"stopping: {e}", file=sys.stderr)
                break
            spent += out.get("_cost_usd") or 0.0
        if not args.dry_run:
            print(f"\nthis run ${spent:.3f} · month to date ${predictor.month_spend(conn):.2f}")
    return 0


def cmd_calibrate(args) -> int:
    """What the blind predictor has learned about its own factor points. Free."""
    from . import calibration

    db.init()
    with db.session() as conn:
        if args.backfill:
            print(f"backfilled {calibration.backfill(conn)} blind picks")
        c = calibration.current(conn)

    print(f"graded blind picks  {c['n_games']}")
    if not c["n_games"]:
        return 0
    print(f"\n{'factor':<15} {'games':>5} {'avg pts':>8} {'correction':>11}")
    for k, f in c["factors"].items():
        print(f"{k:<15} {f['games']:>5} {f['avg_points']:>8.2f} {'x' + format(f['multiplier'], 'g'):>11}")
    print(f"\nmargin error (in-sample)  raw {c['rmse_raw']}  corrected {c['rmse_calibrated']}")
    return 0


def cmd_lessons(args) -> int:
    """The model's habits, counted on every graded blind pick. Free."""
    from . import lessons
    from .sources import nflverse

    db.init()
    season = args.season or config.current_season()
    try:
        pbp = nflverse.pbp([season])
    except Exception:  # noqa: BLE001 -- the tags do not need it
        pbp = None
    with db.session() as conn:
        out = lessons.tally(conn, season, pbp=pbp)

    def line(name, b):
        pct = "--" if b["win_pct"] is None else f"{b['win_pct']:.0%}"
        note = b["verdict"]
        if note == "too few":
            note = f"too few, {b['needs']} more"
        elif "p_value" in b and note != "hindsight":
            note += f" (p {b['p_value']})"
        print(f"  {name:<26} {b['record']:<8} {pct:>4}  {note}")

    for key, title in (("test", f"WEEK {out['start_week']} ON (the test)"),
                       ("hindsight", f"BEFORE WEEK {out['start_week']} (hindsight, not judged)")):
        p = out[key]
        print(f"\n{title}: {p['picks']} graded picks")
        print(" habits")
        for t, b in p["tags"].items():
            line(t, b)
        print(" picks that leaned on a factor (1+ points toward the pick)")
        for k, f in p["factors"].items():
            if f["leaned_on"]["wins"] + f["leaned_on"]["losses"]:
                line(k, f["leaned_on"])
        print(" picks that went against a factor (1+ points the other way)")
        for k, f in p["factors"].items():
            if f["went_against"]["wins"] + f["went_against"]["losses"]:
                line(k, f["went_against"])
        hp = p["how_played"]
        print(" how the game was played, from the play-by-play")
        for res, label in (("loss", "losses"), ("win", "wins")):
            h = hp[res]
            print(f"  {label:<8} out-played {h['outplayed']}, even {h['even']}, "
                  f"won the snaps {h['won_snaps']}"
                  + (f", unknown {h['unknown']}" if h["unknown"] else ""))

    print(f"\nA habit reads 'act' at {out['min_picks']}+ test picks losing at "
          f"p < {out['p_bar']}. Nothing here changes a pick.")
    if args.verbose:
        print()
        for t in out["tag_meaning"].items():
            print(f"  {t[0]}: {t[1]}")
        for g in out["tagged_picks"]:
            print(f"  W{g['week']:<2} {g['game_id']:<18} {g['pick']:<4} {g['result']:<5} "
                  f"{g['how_played'] or '':<10} {', '.join(g['tags'])}")
    return 0


def cmd_shadow_report(args) -> int:
    from . import shadow

    db.init()
    season = args.season or config.current_season()
    with db.session() as conn:
        rep = shadow.report(conn, season)

    def rec(b):
        n = b["w"] + b["l"]
        pct = f"{b['w'] / n:.1%}" if n else "--"
        return f"{b['w']}-{b['l']}-{b['p']} ({pct})"

    print(f"{season}: {rep['games']} finished games with a shadow pick\n")
    print(f"{'':<22}{'shadow':<22}{'live':<22}")
    for key, label in (("winners", "named the winner"), ("ats", "against the spread"),
                       ("dog", "  underdog picks"), ("fav", "  favourite picks")):
        print(f"{label:<22}{rec(rep['shadow'][key]):<22}{rec(rep['live'][key]):<22}")
    print(f"{'avg line value (pts)':<22}{str(rep['shadow']['clv']):<22}{str(rep['live']['clv']):<22}")
    print(f"\nmarket favourite won: {rec(rep['market_favourite_winners'])}")
    for tier, b in sorted(rep["shadow"]["by_tier"].items()):
        print(f"shadow {tier:<10} {rec(b)}")
    return 0


def cmd_report(args) -> int:
    from . import report

    db.init()
    season = args.season or config.current_season()
    with db.session() as conn:
        md, html = report.write(conn, season, args.week)
    print(f"wrote {md}\nwrote {html}")
    if args.open:
        import webbrowser

        webbrowser.open(html.as_uri())
    return 0


def cmd_sync(args) -> int:
    from . import sync

    db.init()
    season = args.season or config.current_season()
    with db.session() as conn:
        out = sync.push(conn, season, week=args.week, snapshot=not args.no_snapshot)
    for k, v in out.items():
        print(f"{k:<14} {v}")
    return 0


def cmd_ratings(args) -> int:
    """Power ratings from final scores. No model calls, no cost."""
    from . import ratings

    season = args.season or config.current_season()
    out = ratings.payload(season, args.week)
    week = out["week"]

    print(f"{season} week {week}   home field {out['home_field']:+.2f}\n")
    for t in out["teams"]:
        ch = "" if t["change"] is None else f"{t['change']:+.1f}"
        print(f"  {t['rank']:>2}  {t['team']:<4} {t['rating']:+6.1f}  {ch}")
    print("\n  game                model   market   (home margin, + = home favoured)")
    for g in out["slate"]:
        mk = "  --" if g["market"] is None else f"{g['market']:+5.1f}"
        pr = "  --" if g["projected"] is None else f"{g['projected']:+5.1f}"
        print(f"  {g['away_team']:>3} @ {g['home_team']:<3}           {pr}   {mk}")

    for label, ev in (("replay " + "-".join(map(str, out["test_seasons"])), out["replay"]),
                      (f"live {season}", out["live"])):
        if not ev.get("games"):
            continue
        a = ev["ats"]["0+"]
        print(
            f"\n  {label}: {ev['games']} games   RMSE model {ev['model']['rmse']} "
            f"vs market {ev['market']['rmse']}   weight on model "
            f"{ev['market_weight']['beta']:+.2f} (se {ev['market_weight']['se']})   "
            f"ATS {a['w']}-{a['l']}-{a['p']} ({a['units']:+.1f}u)"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="edgelord", description="NFL betting prediction bot")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="create the database")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("backfill", help="pull nflverse data and populate games")
    s.add_argument("--seasons", type=int, nargs="+")
    s.add_argument("--refresh", action="store_true", help="ignore the parquet cache")
    s.set_defaults(func=cmd_backfill)

    s = sub.add_parser(
        "refresh",
        help="re-pull the current season, including final scores (needed before grading)",
    )
    s.add_argument("--season", type=int)
    s.set_defaults(func=cmd_refresh)

    s = sub.add_parser("status", help="show what is in the database")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("features", help="build and print the feature pack for one game")
    s.add_argument("--game", required=True, help="game_id, e.g. 2025_01_DAL_PHI")
    s.add_argument("--store", action="store_true", help="also persist to the features table")
    s.add_argument("--gaps-only", action="store_true", help="print just the data_gaps list")
    s.set_defaults(func=cmd_features)

    s = sub.add_parser("poll-odds", help="snapshot current lines from The Odds API")
    s.add_argument("--budget", type=int, help="override the monthly credit ceiling")
    s.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and print but write nothing (still costs one request)",
    )
    s.add_argument(
        "--purge-unmatched",
        action="store_true",
        help="delete stored snapshots that never matched a scheduled game",
    )
    s.add_argument("--season", type=int)
    s.set_defaults(func=cmd_poll_odds)

    s = sub.add_parser(
        "snapshot-lines",
        help="record the current nflverse line (free, no API key)",
    )
    s.add_argument("--season", type=int)
    s.set_defaults(func=cmd_snapshot_lines)

    s = sub.add_parser(
        "recheck",
        help="flag live picks whose line or key injuries changed; rerun them within a weekly cap",
    )
    s.add_argument("--season", type=int)
    s.add_argument("--week", type=int, required=True)
    s.add_argument(
        "--run", action="store_true",
        help="re-predict flagged games while this week's recheck spend stays under the cap",
    )
    s.add_argument(
        "--cap", type=float,
        help=f"weekly USD cap for --run (default EDGELORD_RECHECK_WEEKLY_USD, now {config.RECHECK_WEEKLY_USD:g})",
    )
    s.add_argument(
        "--allow", type=float,
        help="USD this run may spend on top of the week's recheck spend so far (a manual, confirmed run)",
    )
    s.set_defaults(func=cmd_recheck)

    s = sub.add_parser("predict", help="run the model over one game or a whole slate")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--game", help="single game_id")
    g.add_argument("--week", type=int, help="whole slate for this week")
    s.add_argument("--season", type=int)
    s.add_argument("--label", default="manual", help="run label: sunday, thursday, monday")
    s.add_argument(
        "--effort",
        default=None,
        choices=["low", "medium", "high", "xhigh", "max"],
        help=f"thinking depth and token spend (default {config.PREDICT_EFFORT})",
    )
    s.add_argument(
        "--only-moved",
        action="store_true",
        help="skip games whose line has not crossed a key number since the last run",
    )
    s.add_argument("--dry-run", action="store_true", help="print the prompt, call nothing")
    s.add_argument("--verbose", action="store_true", help="print each paragraph")
    s.set_defaults(func=cmd_predict)

    s = sub.add_parser("grade", help="grade finished games and show the running record")
    s.add_argument("--season", type=int)
    s.add_argument("--regrade", action="store_true", help="recompute already-graded rows")
    s.set_defaults(func=cmd_grade)

    s = sub.add_parser(
        "postmortem",
        help="explain why each losing pick lost, so the misses are on record",
    )
    s.add_argument("--season", type=int)
    s.add_argument("--week", type=int)
    s.add_argument(
        "--regenerate", action="store_true",
        help="redo losses that already have a post-mortem",
    )
    s.add_argument(
        "--no-model", action="store_true",
        help="compute the miss arithmetic only, with no model call and no cost",
    )
    s.add_argument("--limit", type=int, help="stop after this many losses")
    s.set_defaults(func=cmd_postmortem)

    s = sub.add_parser(
        "shadow",
        help="blind predictor: who wins from the factors, the line compared last (separate table)",
    )
    s.add_argument("--week", type=int)
    s.add_argument("--season", type=int)
    s.add_argument("--game", help="one game_id instead of the slate")
    s.add_argument("--effort", choices=["low", "medium", "high", "max"])
    s.add_argument("--dry-run", action="store_true", help="print the prompt, call nothing")
    s.add_argument("--verbose", action="store_true")
    s.add_argument(
        "--official", action="store_true",
        help="store as the official pick (predictions table, record, site) instead of a shadow",
    )
    s.set_defaults(func=cmd_shadow)

    s = sub.add_parser("shadow-report", help="shadow picks graded beside the live ones")
    s.add_argument("--season", type=int)
    s.set_defaults(func=cmd_shadow_report)

    s = sub.add_parser(
        "calibrate",
        help="show the learned corrections to the blind predictor's factor points",
    )
    s.add_argument(
        "--backfill", action="store_true",
        help="reconstruct factor points for blind picks made before they were stored",
    )
    s.set_defaults(func=cmd_calibrate)

    s = sub.add_parser(
        "lessons",
        help="the model's habits counted on every graded pick, wins and losses (no cost)",
    )
    s.add_argument("--season", type=int)
    s.add_argument("--verbose", action="store_true", help="list each tagged pick")
    s.set_defaults(func=cmd_lessons)

    s = sub.add_parser("report", help="render the slate report")
    s.add_argument("--week", type=int, required=True)
    s.add_argument("--season", type=int)
    s.add_argument("--open", action="store_true", help="open the HTML report")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser(
        "confidence", help="how much the record itself should be believed"
    )
    s.add_argument("--season", type=int)
    s.set_defaults(func=cmd_confidence)

    s = sub.add_parser("spend", help="model spend by month and model")
    s.set_defaults(func=cmd_spend)

    s = sub.add_parser(
        "ratings", help="power ratings from final scores, with the replay verdict (no cost)"
    )
    s.add_argument("--season", type=int)
    s.add_argument("--week", type=int, help="ratings as of this week (default: next week with games to play)")
    s.set_defaults(func=cmd_ratings)

    s = sub.add_parser("sync", help="mirror predictions and record to Firestore")
    s.add_argument("--season", type=int)
    s.add_argument("--week", type=int, help="limit to one week")
    s.add_argument("--no-snapshot", action="store_true", help="skip the local JSON snapshot")
    s.set_defaults(func=cmd_sync)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
