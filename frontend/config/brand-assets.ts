/**
 * Mapa central dos assets oficiais encontrados no projeto (public/assets/brand).
 * Para trocar uma imagem, substitua o arquivo ou ajuste o caminho aqui; nenhum componente referencia caminhos direto.
 * Assets ausentes ficam como null e o AssetImage mostra um placeholder neutro.
 */
export type BrandAsset = { src: string; width: number; height: number; alt: string };

export const BRAND_ASSETS = {
  nfeIcon: { src: "/assets/brand/nfe-icon.png", width: 1254, height: 1254, alt: "Planning & Scheduling NFE" },
  planningLogo: { src: "/assets/brand/planning-nfe-logo.png", width: 1536, height: 1024, alt: "Planning & Scheduling NFE Digital" },
} satisfies Record<string, BrandAsset | null>;

export const APP_BRAND = {
  name: "Planning & Scheduling Michelin",
  subtitle: "Planejamento e Programação da Manutenção",
  context: "NFE",
} as const;
