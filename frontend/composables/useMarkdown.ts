import { marked, type Renderer } from "marked";

// Disable raw HTML passthrough — only parse markdown constructs.
// This prevents any LLM-generated <script>/<iframe> from reaching the DOM.
const renderer: Partial<Renderer> = {
  html() {
    return "";
  },
};

marked.use({
  gfm: true,
  breaks: true,
  renderer,
});

export function useMarkdown() {
  function render(source: string): string {
    if (!source) return "";
    return marked.parse(source) as string;
  }

  return { render };
}
