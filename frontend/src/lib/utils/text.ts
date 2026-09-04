/** Remove HTML tags, but leave math comparisons like "score < 60" / "x > 0" intact. */
export function stripHtml(input: string): string {
  return input.replace(/<\/?[a-zA-Z][a-zA-Z0-9-]*(?:\s[^<>]*)?\/?>/g, "");
}

/** Reduce markdown + HTML to clean plain text (for previews/snippets). */
export function toPlainText(input: string): string {
  return stripHtml(input)
    .replace(/```[\s\S]*?```/g, "")            // code fences
    .replace(/`([^`]+)`/g, "$1")                // inline code
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")   // images -> alt
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")    // links -> text
    .replace(/^#{1,6}\s+/gm, "")                // headings
    .replace(/(\*\*|__)(.*?)\1/g, "$2")         // bold
    .replace(/(\*|_)(.*?)\1/g, "$2")            // italic
    .replace(/^\s*[-*+]\s+/gm, "")              // unordered list markers
    .replace(/^\s*\d+\.\s+/gm, "")              // ordered list markers
    .replace(/^\s*>\s?/gm, "")                  // blockquotes
    .replace(/\s+/g, " ")                       // collapse whitespace
    .trim();
}

/**
 * Remove os marcadores "[Fonte: título — url]" que o modelo copia do contexto das
 * ferramentas para o corpo da resposta. As fontes já chegam pelo evento `sources`
 * e vivem no bloco recolhível ("N fontes") — no texto elas só poluem. Também
 * apaga um marcador ainda aberto no fim (chega token a token durante o stream)
 * e colapsa as linhas vazias que sobram.
 */
export function stripSourceMarkers(input: string): string {
  return input
    .replace(/[ \t]*\[Fonte:[^\]]*\]/g, "") // marcador completo
    .replace(/[ \t]*\[Fonte:[^\]]*$/, "")  // marcador incompleto no fim (streaming)
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
