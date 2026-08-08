import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type AnchorHTMLAttributes,
  type MouseEvent,
  type ReactNode,
} from "react";

interface RouteDef {
  path: string;
  element: ReactNode;
}

interface MatchResult {
  pathname: string;
  params: Record<string, string>;
}

interface RouterContextValue {
  match: MatchResult | null;
  push: (to: string) => void;
  outlet: ReactNode;
}

const RouterContext = createContext<RouterContextValue | null>(null);

const ROOT_REDIRECT_TARGET = "/dashboard";

function matchPath(
  pattern: string,
  pathname: string,
): Record<string, string> | null {
  if (pattern === pathname) return {};
  const patternParts = pattern.split("/").filter(Boolean);
  const pathParts = pathname.split("/").filter(Boolean);
  if (patternParts.length !== pathParts.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < patternParts.length; i += 1) {
    const pat = patternParts[i];
    const seg = pathParts[i];
    if (pat.startsWith(":")) {
      params[pat.slice(1)] = decodeURIComponent(seg);
    } else if (pat !== seg) {
      return null;
    }
  }
  return params;
}

function readInitialPathname(): string {
  if (typeof window === "undefined") return ROOT_REDIRECT_TARGET;
  if (
    window.location.pathname === "/" ||
    window.location.pathname === ""
  ) {
    window.history.replaceState(null, "", ROOT_REDIRECT_TARGET);
    return ROOT_REDIRECT_TARGET;
  }
  return window.location.pathname;
}

interface RouterProps {
  routes: RouteDef[];
  fallback?: ReactNode;
  children?: ReactNode;
}

export function Router({ routes, fallback, children }: RouterProps) {
  const [pathname, setPathname] = useState<string>(readInitialPathname);

  useEffect(() => {
    const handlePopState = () => {
      setPathname(window.location.pathname);
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const push = useCallback((to: string) => {
    if (typeof window === "undefined") return;
    if (window.location.pathname === to) return;
    window.history.pushState(null, "", to);
    setPathname(to);
  }, []);

  const { match, element } = useMemo(() => {
    for (const route of routes) {
      const params = matchPath(route.path, pathname);
      if (params) {
        return {
          match: { pathname, params } as MatchResult,
          element: route.element,
        };
      }
    }
    return { match: null as MatchResult | null, element: fallback ?? null };
  }, [routes, pathname, fallback]);

  const contextValue = useMemo<RouterContextValue>(
    () => ({ match, push, outlet: element }),
    [match, push, element],
  );

  return (
    <RouterContext.Provider value={contextValue}>
      {children ?? element}
    </RouterContext.Provider>
  );
}

export function RouterOutlet() {
  const ctx = useContext(RouterContext);
  if (!ctx) {
    throw new Error("RouterOutlet must be used inside <Router>");
  }
  return <>{ctx.outlet}</>;
}

export function useNavigate(): (to: string) => void {
  const ctx = useContext(RouterContext);
  if (!ctx) {
    throw new Error("useNavigate must be used inside <Router>");
  }
  return ctx.push;
}

export function useParams<T = Record<string, string>>(): T {
  const ctx = useContext(RouterContext);
  if (!ctx) {
    throw new Error("useParams must be used inside <Router>");
  }
  return (ctx.match?.params ?? {}) as T;
}

interface NavLinkRenderProps {
  isActive: boolean;
}

interface NavLinkProps
  extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href" | "className"> {
  to: string;
  className?: string | ((state: NavLinkRenderProps) => string);
  children?: ReactNode;
}

export function NavLink({
  to,
  className,
  children,
  onClick,
  ...rest
}: NavLinkProps) {
  const ctx = useContext(RouterContext);
  if (!ctx) {
    throw new Error("NavLink must be used inside <Router>");
  }
  const currentPath = ctx.match?.pathname ?? "/";
  const isActive = currentPath === to || currentPath.startsWith(`${to}/`);

  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.defaultPrevented) return;
    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      onClick?.(event);
      return;
    }
    event.preventDefault();
    ctx.push(to);
    onClick?.(event);
  };

  const resolvedClassName =
    typeof className === "function" ? className({ isActive }) : className;

  return (
    <a href={to} onClick={handleClick} className={resolvedClassName} {...rest}>
      {children}
    </a>
  );
}
