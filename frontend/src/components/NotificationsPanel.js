import { useCallback, useEffect, useState } from "react";
import { Bell, BellOff, Loader2, Mail, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { useApp } from "@/context/AppContext";
import {
  currentSubscription,
  disablePush,
  enablePush,
  iosNeedsInstall,
  pushSupported,
  sendTestPush,
} from "@/lib/push";
import http from "@/lib/api";

const EVENTS = [
  ["saved_search", "evSavedSearch"],
  ["price_drop", "evPriceDrop"],
  ["shipment", "evShipment"],
  ["enquiry", "evEnquiry"],
];

const Toggles = ({ channel, prefs, onChange, t }) => (
  <div className="mt-3">
    <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
      {t("notifyWhat")}
    </div>
    <ul className="mt-2 divide-y divide-border">
      {EVENTS.map(([key, label]) => (
        <li key={key} className="flex items-center justify-between gap-4 py-2.5">
          <span className="text-[13.5px] text-foreground">{t(label)}</span>
          <Switch
            data-testid={`notify-${channel}-${key}`}
            checked={Boolean(prefs[key])}
            onCheckedChange={(v) => onChange({ ...prefs, [key]: v })}
          />
        </li>
      ))}
    </ul>
  </div>
);

/**
 * Push and email preferences.
 *
 * Both channels answer to the same four switches, so turning off "price drop" silences it
 * everywhere. Push is per-DEVICE (a browser subscription), which is why the button reflects
 * this device while the count reflects the account.
 */
export const NotificationsPanel = () => {
  const { t } = useApp();
  const [prefs, setPrefs] = useState(null);
  const [devices, setDevices] = useState(0);
  const [here, setHere] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await http.get("/notifications");
      setPrefs(data.prefs);
      setDevices(data.devices || 0);
      setHere(Boolean(await currentSubscription()));
    } catch (e) {
      setPrefs(null);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const persist = async (next) => {
    setPrefs(next);
    try {
      await http.put("/notifications", next);
    } catch (e) {
      toast.error("could not save that");
      load();
    }
  };

  const turnOn = async () => {
    setBusy(true);
    try {
      await enablePush();
      await load();
      toast.success(t("pushOn"));
    } catch (e) {
      toast.error(
        e?.message === "denied"
          ? t("pushDenied")
          : e?.message === "unsupported"
            ? t("pushUnsupported")
            : e?.response?.data?.detail || String(e?.message || e)
      );
    } finally {
      setBusy(false);
    }
  };

  const turnOff = async () => {
    setBusy(true);
    try {
      await disablePush();
      await load();
    } catch (e) {
      toast.error("could not turn them off");
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    setBusy(true);
    try {
      await sendTestPush();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "the test could not be sent");
    } finally {
      setBusy(false);
    }
  };

  if (!prefs) return null;

  return (
    <>
      <section
        data-testid="account-push"
        className="mt-6 rounded-[16px] border border-border bg-card p-5 shadow-sm"
      >
        <h2 className="flex items-center gap-2 text-[14.5px] font-semibold text-foreground">
          <Bell className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
          {t("pushTitle")}
        </h2>
        <p className="mt-1 max-w-xl text-[12.5px] leading-relaxed text-muted-foreground">
          {t("pushBlurb")}
        </p>

        {iosNeedsInstall() && (
          <p
            data-testid="account-push-ios"
            className="mt-3 rounded-[10px] border border-border bg-secondary px-3 py-2.5 text-[12.5px] leading-relaxed text-foreground"
          >
            {t("pushIosHint")}
          </p>
        )}

        {!pushSupported() ? (
          <p className="mt-3 text-[12.5px] text-muted-foreground">{t("pushUnsupported")}</p>
        ) : (
          <div className="mt-4 flex flex-wrap items-center gap-2">
            {here ? (
              <Button
                data-testid="account-push-off"
                variant="outline"
                onClick={turnOff}
                disabled={busy}
                className="h-10 gap-2 rounded-[10px] border-border bg-card px-4 text-[13.5px]"
              >
                <BellOff className="h-4 w-4" aria-hidden="true" />
                {t("pushDisable")}
              </Button>
            ) : (
              <Button
                data-testid="account-push-on"
                onClick={turnOn}
                disabled={busy}
                className="h-10 gap-2 rounded-[10px] bg-[hsl(var(--primary))] px-4 text-[13.5px] font-semibold text-primary-foreground hover:brightness-110"
              >
                {busy ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Bell className="h-4 w-4" aria-hidden="true" />
                )}
                {t("pushEnable")}
              </Button>
            )}

            {here && (
              <Button
                data-testid="account-push-test"
                variant="ghost"
                onClick={test}
                disabled={busy}
                className="h-10 gap-2 rounded-[10px] px-3 text-[13.5px] text-muted-foreground hover:text-foreground"
              >
                <Send className="h-4 w-4" aria-hidden="true" />
                {t("pushTest")}
              </Button>
            )}

            {devices > 0 && (
              <span className="tnum text-[12px] text-muted-foreground">
                {devices} {t("pushDevices")}
              </span>
            )}
          </div>
        )}

        <Toggles
          channel="push"
          prefs={prefs.push}
          t={t}
          onChange={(push) => persist({ ...prefs, push })}
        />
      </section>

      <section
        data-testid="account-email-notifications"
        className="mt-6 rounded-[16px] border border-border bg-card p-5 shadow-sm"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-[14.5px] font-semibold text-foreground">
              <Mail className="h-4 w-4 text-[hsl(var(--primary))]" aria-hidden="true" />
              {t("emailTitle")}
            </h2>
            <p className="mt-1 max-w-xl text-[12.5px] leading-relaxed text-muted-foreground">
              {t("emailBlurb")}
            </p>
          </div>
          <Switch
            data-testid="notify-email-enabled"
            checked={Boolean(prefs.email.enabled)}
            onCheckedChange={(v) =>
              persist({ ...prefs, email: { ...prefs.email, enabled: v } })
            }
          />
        </div>

        <Toggles
          channel="email"
          prefs={prefs.email}
          t={t}
          onChange={(email) => persist({ ...prefs, email })}
        />
      </section>
    </>
  );
};

export default NotificationsPanel;
