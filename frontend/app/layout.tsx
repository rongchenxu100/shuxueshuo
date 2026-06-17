import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "数学可视化生成台",
  description: "在线生成和管理数学可视化网页的创作后台",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="flex h-screen flex-col">{children}</body>
    </html>
  );
}
