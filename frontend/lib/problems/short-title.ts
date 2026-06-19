const MAX_SHORT_TITLE_LENGTH = 18;

export function deriveProblemShortTitle(title: string): string {
  const normalizedTitle = title.replace(/\s+/g, " ").trim();

  if (!normalizedTitle) {
    return "新建题目";
  }

  const tianjinMockExamMatch = normalizedTitle.match(
    /天津市([^区县市]+)[区县].*?([一二三四]模).*?(?:第\s*)?(\d+)\s*题/u,
  );

  if (tianjinMockExamMatch) {
    return `${tianjinMockExamMatch[1]}${tianjinMockExamMatch[2]} ${tianjinMockExamMatch[3]}题`;
  }

  return normalizedTitle.length > MAX_SHORT_TITLE_LENGTH
    ? normalizedTitle.slice(0, MAX_SHORT_TITLE_LENGTH)
    : normalizedTitle;
}
