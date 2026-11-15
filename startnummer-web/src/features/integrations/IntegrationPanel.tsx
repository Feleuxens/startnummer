import type { ReactNode } from 'react';

export default function IntegrationPanel({
  name,
  description,
  children,
}: {
  name: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <details className="integration-panel">
      <summary>
        <span className="integration-summary">
          <span className="integration-name">{name}</span>
          <span className="integration-state">{description}</span>
        </span>
      </summary>
      <div className="integration-settings">{children}</div>
    </details>
  );
}
