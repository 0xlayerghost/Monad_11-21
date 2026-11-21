import MarkdownIt from 'markdown-it'

const markdown = new MarkdownIt({ html: false, linkify: false, breaks: false })

export function renderInvestigationAnswer(answer: string): string {
  return markdown.render(answer)
}
