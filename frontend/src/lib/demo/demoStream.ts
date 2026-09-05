import type { AskEvent, AskInput } from "../types";
import { DEMO_ANSWER, DEMO_ANSWER_CITATIONS } from "./demoData";

const ERROR_SENTINEL = "[demo-error]";

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function* demoStream(input: AskInput): AsyncGenerator<AskEvent> {
  const conversationId = input.conversationId ?? "demo-new";
  yield { type: "run_started", conversationId };

  if (input.question.includes(ERROR_SENTINEL)) {
    await delay(400);
    yield { type: "error", message: "Não consegui gerar a resposta agora. Tente novamente." };
    return;
  }

  yield { type: "step", name: "gate", phase: "started" };
  await delay(300);
  yield { type: "step", name: "gate", phase: "finished", detail: { retrieve: true, degraded: false } };
  yield { type: "step", name: "retrieve", phase: "started" };
  await delay(300);
  yield { type: "step", name: "retrieve", phase: "finished", detail: { kept: DEMO_ANSWER_CITATIONS.length } };
  yield { type: "step", name: "answer", phase: "started" };
  await delay(200);
  for (const word of DEMO_ANSWER.split(" ")) {
    yield { type: "token", text: word + " " };
    await delay(40);
  }
  yield { type: "step", name: "answer", phase: "finished" };
  yield { type: "sources", citations: DEMO_ANSWER_CITATIONS };
  yield { type: "done" };
}
