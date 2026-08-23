import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Edgelord",
  description: "NFL prediction tracking",
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0f1113",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">{children}</div>
      </body>
    </html>
  );
}
