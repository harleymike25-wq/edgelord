"""Computed prediction models -- no model calls, no cost.

Each model projects every game's home margin from what was known before
kickoff, walking forward one week at a time so a game is never projected from
its own result. They share one report card (`common.report_card`) so they can
be compared with each other and with the closing line on the same games.

- `elo`: a rating from final scores, updated game by game, with home field,
  rest and margin of victory.
- `qb`: the Elo rating adjusted for who is actually starting at quarterback.

The existing least-squares rating (`edgelord.ratings`) reports through the same
card for comparison.
"""
