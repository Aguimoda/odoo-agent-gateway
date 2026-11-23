import { BarChart3, Plug, ShieldOff, SlidersHorizontal } from "lucide-react";
import { NavLink, Navigate, useParams } from "react-router";

import { useI18n } from "../i18n";
import { useSession } from "../session";
import { Shell } from "../shell/Shell";
import { ProvidersTab } from "./ProvidersTab";
import { SettingsTab } from "./SettingsTab";
import { UsageTab } from "./UsageTab";

const TABS = [
  { id: "providers", key: "admin.providers", icon: Plug },
  { id: "settings", key: "admin.settings", icon: SlidersHorizontal },
  { id: "usage", key: "admin.usage", icon: BarChart3 },
] as const;

export function AdminPage() {
  const { t } = useI18n();
  const { me } = useSession();
  const { section } = useParams();

  if (!section) return <Navigate to="/admin/providers" replace />;
  const current = TABS.find((tab) => tab.id === section);
  if (!current) return <Navigate to="/admin/providers" replace />;

  return (
    <Shell title={t("admin.title")}>
      <div className="page">
        <div className="page-inner">
          <div className="page-head">
            <h1>{t("admin.title")}</h1>
            <p>{t("admin.lead")}</p>
          </div>
          {!me?.is_admin ? (
            // Hiding is a convenience; the admin API checks the Odoo group on every call.
            <div className="panel empty">
              <span className="empty-icon">
                <ShieldOff aria-hidden />
              </span>
              <h3>{t("admin.forbidden")}</h3>
            </div>
          ) : (
            <>
              <nav className="tabs" aria-label={t("admin.title")} style={{ marginBottom: "var(--space-5)" }}>
                {TABS.map(({ id, key, icon: Icon }) => (
                  <NavLink key={id} to={`/admin/${id}`} className="tab">
                    <Icon size={16} aria-hidden />
                    {t(key)}
                  </NavLink>
                ))}
              </nav>
              {current.id === "providers" && <ProvidersTab />}
              {current.id === "settings" && <SettingsTab />}
              {current.id === "usage" && <UsageTab />}
            </>
          )}
        </div>
      </div>
    </Shell>
  );
}
