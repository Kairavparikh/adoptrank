import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "AdoptRank — Find open source that actually fits",
  description: "Search open-source repositories ranked by code evidence, sustained adoption, and compatibility with your project.",
  icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
  openGraph: {
    title: "AdoptRank — Find open source that actually fits",
    description: "Repository search backed by code evidence, real adoption, and project compatibility.",
    type: "website",
    images: [{ url: "/og.png", width: 1200, height: 630, alt: "AdoptRank — Find open source that actually fits." }],
  },
  twitter: {
    card: "summary_large_image",
    title: "AdoptRank — Find open source that actually fits",
    description: "Repository search backed by code evidence, real adoption, and project compatibility.",
    images: ["/og.png"],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body className={`${geistSans.variable} ${geistMono.variable}`}>{children}</body></html>;
}
