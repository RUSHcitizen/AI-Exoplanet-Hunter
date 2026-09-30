import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Exoplanet Hunter — TESS light-curve research pipeline",
    template: "%s · Exoplanet Hunter",
  },
  description:
    "An open, reproducible pipeline for NASA TESS photometry: quality filtering, gap-aware segmentation, normalization, and outlier flagging on real observations, with transit search and candidate ranking in development.",
};

export const viewport: Viewport = {
  themeColor: "#0a0b0d",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col bg-page-plane font-sans text-ink-primary">
        <SiteHeader />
        <div id="main" className="relative z-10 flex flex-1 flex-col">
          {children}
        </div>
        <SiteFooter />
      </body>
    </html>
  );
}
