import type { Metadata } from "next";
import { Unbounded } from "next/font/google";
import "./globals.css";

// The logo face only. Body text stays on the system stack.
const display = Unbounded({
  subsets: ["latin"],
  weight: ["800"],
  variable: "--font-display",
});

export const metadata: Metadata = {
  title: "Edgelord",
  description: "Beat the Edge — NFL picks, tracked and graded",
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0f1113",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={display.variable}>
      <body>
        <div className="shell">{children}</div>
      </body>
    </html>
  );
}
