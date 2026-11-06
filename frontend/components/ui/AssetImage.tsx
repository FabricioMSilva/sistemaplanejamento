import Image from "next/image";
import { useState } from "react";
import { ImageOff } from "lucide-react";
import type { BrandAsset } from "@/config/brand-assets";
import { cn } from "@/lib/utils";

type AssetImageProps = {
  asset: BrandAsset | null;
  /** Altura exibida em px; a largura segue a proporção original do arquivo. */
  height: number;
  className?: string;
  priority?: boolean;
  decorative?: boolean;
};

export default function AssetImage({ asset, height, className, priority, decorative }: AssetImageProps) {
  const [failed, setFailed] = useState(false);
  if (!asset || failed) {
    return (
      <span role="img" aria-label={decorative ? undefined : "Imagem indisponível"} aria-hidden={decorative || undefined}
        className={cn("inline-flex items-center justify-center rounded-md border border-dashed border-border bg-muted text-muted-foreground", className)}
        style={{ height, width: height }}>
        <ImageOff size={Math.max(14, height * 0.45)} />
      </span>
    );
  }
  const width = Math.round((asset.width / asset.height) * height);
  return (
    <Image src={asset.src} width={width} height={height} alt={decorative ? "" : asset.alt} priority={priority}
      className={cn("object-contain", className)} style={{ height, width }} onError={() => setFailed(true)} />
  );
}
