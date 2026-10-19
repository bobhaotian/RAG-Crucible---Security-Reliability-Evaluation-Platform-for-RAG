// One panel that throws must not blank the whole run view. React unmounts the
// entire tree on an uncaught render error, so without this a single bad metric
// takes every other panel down with it.
//
// A boundary resets when its `key` changes, so callers key it on whatever the
// user can change (the selected run, the compared run, the open drill). A
// boundary given `onClose` can also be dismissed, by its button or by Escape.

import { Component, useEffect } from "react";
import type { ErrorInfo, ReactNode } from "react";

interface Props {
  title: string;
  children: ReactNode;
  /** Dismisses the failed view, e.g. closes the evidence drawer. */
  onClose?: () => void;
  /** Render the failure where the drawer would have been, rather than as a panel. */
  variant?: "panel" | "drawer";
}

interface State {
  error: Error | null;
}

export class PanelBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`panel "${this.props.title}" failed to render`, error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    const { title, onClose, variant = "panel" } = this.props;
    const head = (
      <div className="panel-head">
        <h3>{title}</h3>
        {onClose && (
          <button className="drill" onClick={onClose}>
            close ✕
          </button>
        )}
      </div>
    );
    const message = (
      <p>
        This view could not be drawn: <code>{error.message}</code>. The rest of the run is
        unaffected; the raw metrics are in <code>/runs/&lt;id&gt;/results</code>.
      </p>
    );
    if (variant === "drawer") {
      return (
        <>
          <div className="drawer-backdrop" onClick={onClose} />
          <aside className="drawer panel-error" role="alert">
            {head}
            {message}
            {onClose && <CloseOnEscape onClose={onClose} />}
          </aside>
        </>
      );
    }
    return (
      <section className="panel panel-error" role="alert">
        {head}
        {message}
        {onClose && <CloseOnEscape onClose={onClose} />}
      </section>
    );
  }
}

/** Escape still closes a view whose own key handler went down with it. */
function CloseOnEscape({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return null;
}
