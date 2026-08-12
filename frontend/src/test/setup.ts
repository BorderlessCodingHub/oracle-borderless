import "@testing-library/jest-dom";

// jsdom não implementa Element.scrollTo; o ChatPage usa para rolar o thread
// até o fim a cada turno. Sem o polyfill, montar o ChatPage em teste explode.
// Guardado por typeof porque alguns arquivos de teste rodam em ambiente
// "node" (ex.: @vitest-environment node), onde `Element` nem existe.
if (typeof Element !== "undefined" && !Element.prototype.scrollTo) {
  Element.prototype.scrollTo = function scrollTo() {};
}
