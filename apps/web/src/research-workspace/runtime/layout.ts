import type { ResearchWidgetPage } from "./types";

export interface ResearchFixedLayout {
  readonly widgetKeys: ReadonlyArray<string>;
}

export function orderVisibleWidgetKeys(
  widgetKeys: ReadonlyArray<string>,
  visibleKeys: ReadonlySet<string> | ReadonlyArray<string> = widgetKeys,
): ReadonlyArray<string> {
  const visible = visibleKeys instanceof Set ? visibleKeys : new Set(visibleKeys);
  return widgetKeys.filter((key, index) => visible.has(key) && widgetKeys.indexOf(key) === index);
}

export function getFixedLayout(
  widgetKeys: ReadonlyArray<string>,
  page: ResearchWidgetPage,
  definitions: ReadonlyArray<{ key: string; supportedPages: ReadonlyArray<ResearchWidgetPage> }>,
  visibleKeys?: ReadonlySet<string> | ReadonlyArray<string>,
): ResearchFixedLayout {
  const supported = new Set(
    definitions
      .filter((definition) => definition.supportedPages.includes(page))
      .map((definition) => definition.key),
  );
  return {
    widgetKeys: orderVisibleWidgetKeys(
      widgetKeys.filter((key) => supported.has(key)),
      visibleKeys,
    ),
  };
}
