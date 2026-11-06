import { Head, Html, Main, NextScript } from "next/document";
import { DEFAULT_THEME, THEME_BOOT_SCRIPT } from "@/config/themes";

export default function Document() {
  return (
    <Html lang="pt-BR" data-theme={DEFAULT_THEME} suppressHydrationWarning>
      <Head>
        <meta name="application-name" content="Planning & Scheduling Michelin" />
        <meta name="description" content="Planning & Scheduling Michelin · Planejamento e Programação da Manutenção" />
        <link rel="icon" type="image/png" href="/assets/brand/nfe-icon.png" />
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </Head>
      <body>
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
