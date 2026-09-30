import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Pi Mensae · TESS Sector 1",
  description:
    "Real TESS Sector 1 photometry of Pi Mensae (TIC 261136679), processed through quality filtering, gap-aware segmentation, normalization, and robust outlier flagging.",
};

export default function PiMensaeLayout({ children }: { children: React.ReactNode }) {
  return children;
}
