/** Rótulos da linha do tempo do turno. Só aqui o nome técnico do passo/tool
 * vira frase para a pessoa. `fetch_notion_page` NÃO mostra o page_id: é ruído. */

export function stepLabel(name: string, detail?: Record<string, unknown>): string {
  switch (name) {
    case "gate":
      return "Entendendo a pergunta";
    case "retrieve": {
      const kept = detail?.kept;
      if (typeof kept === "number") return `Buscando na base · ${kept} ${kept === 1 ? "trecho" : "trechos"}`;
      return "Buscando na base";
    }
    case "refuse":
      return "Nada na base cobre essa pergunta";
    case "answer":
      return "Respondendo";
    default:
      return name;
  }
}

export function toolLabel(name: string, args?: Record<string, unknown>): string {
  switch (name) {
    case "web_search": {
      const query = args?.query;
      return typeof query === "string" && query ? `Buscando na web: «${query}»` : "Buscando na web";
    }
    case "fetch_notion_page":
      return "Lendo página do Notion";
    default:
      return name;
  }
}
