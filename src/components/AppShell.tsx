import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

interface AppShellProps {
  children: ReactNode;
}

/**
 * Sidebar + main-outlet layout that wraps the app's routes. Stays pure:
 * no data fetching, no router state of its own — only renders nav links
 * and slots children into the main column.
 */
export function AppShell({ children }: AppShellProps) {
  return (
    <div className="flex min-h-screen bg-slate-50">
      <nav
        aria-label="Primary"
        className="flex w-56 shrink-0 flex-col border-r border-slate-200 bg-white px-3 py-6"
      >
        <div className="px-2 pb-4 text-sm font-semibold tracking-tight text-slate-700">
          MACS+ Automation
        </div>
        <ul className="space-y-1">
          <li>
            <ShellNavLink to="/" end label="New Run" />
          </li>
          <li>
            <ShellNavLink to="/runs" label="History" />
          </li>
        </ul>
      </nav>
      <main className="flex-1">{children}</main>
    </div>
  );
}

function ShellNavLink({
  to,
  label,
  end,
}: {
  to: string;
  label: string;
  end?: boolean;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        [
          "block rounded-md px-3 py-2 text-sm font-medium transition-colors",
          isActive
            ? "bg-blue-50 text-blue-800"
            : "text-slate-700 hover:bg-slate-100",
        ].join(" ")
      }
    >
      {label}
    </NavLink>
  );
}
