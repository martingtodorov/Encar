import { useState } from "react";
import { MessageSquarePlus, Loader2, Send } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";
import http from "@/lib/api";

/**
 * Buyer enquiry about one car.
 *
 * Deliberately usable as a GUEST: requiring an account before a buyer can ask a
 * question would lose the enquiry. Signing in only pre-fills the contact fields.
 */
export const EnquiryDialog = ({ car, title }) => {
  const { t, lang } = useApp();
  const { user } = useAuth();

  const [open, setOpen] = useState(false);
  const [sending, setSending] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", phone: "", message: "" });

  const set = (k) => (e) => setForm((p) => ({ ...p, [k]: e.target.value }));

  const name = form.name || user?.name || "";
  const email = form.email || user?.email || "";
  // A signed-in buyer has already given us their number; asking for it again loses enquiries.
  const phone = form.phone || user?.phone || "";

  const submit = async (e) => {
    e.preventDefault();
    if (!email.trim() && !phone.trim()) {
      toast.error(t("enquiryNeedContact"));
      return;
    }
    setSending(true);
    try {
      await http.post("/enquiry", {
        listing_id: car?.id || "",
        car_title: title || "",
        name,
        email,
        phone,
        message: form.message,
        lang,
      });
      toast.success(t("enquirySent"));
      setOpen(false);
      setForm({ name: "", email: "", phone: "", message: "" });
    } catch (err) {
      toast.error(err?.response?.data?.detail || t("enquiryFailed"));
    } finally {
      setSending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          data-testid="enquiry-open-button"
          className="h-12 w-full justify-center gap-2 rounded-[12px] bg-[hsl(var(--primary))] text-[15px] font-semibold text-primary-foreground hover:brightness-110"
        >
          <MessageSquarePlus className="h-[18px] w-[18px]" aria-hidden="true" />
          {t("sendEnquiry")}
        </Button>
      </DialogTrigger>

      <DialogContent data-testid="enquiry-dialog" className="max-w-[440px] bg-card">
        <DialogHeader>
          <DialogTitle className="text-[17px]">{t("sendEnquiry")}</DialogTitle>
          <DialogDescription className="text-[13px] leading-relaxed">
            {user ? t("enquiryBlurbUser") : t("enquiryBlurbGuest")}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={submit} className="flex flex-col gap-3.5" data-testid="enquiry-form">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="enq-name" className="text-[12.5px] font-medium">
              {t("nameLabel")}
            </Label>
            <Input
              id="enq-name"
              data-testid="enquiry-name-input"
              value={name}
              onChange={set("name")}
              autoComplete="name"
              className="h-11 rounded-[10px] bg-card"
            />
          </div>

          <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="enq-email" className="text-[12.5px] font-medium">
                {t("emailLabel")}
              </Label>
              <Input
                id="enq-email"
                data-testid="enquiry-email-input"
                type="email"
                value={email}
                onChange={set("email")}
                autoComplete="email"
                className="h-11 rounded-[10px] bg-card"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="enq-phone" className="text-[12.5px] font-medium">
                {t("phoneLabel")}
              </Label>
              <Input
                id="enq-phone"
                data-testid="enquiry-phone-input"
                type="tel"
                value={phone}
                onChange={set("phone")}
                autoComplete="tel"
                className="h-11 rounded-[10px] bg-card"
              />
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="enq-message" className="text-[12.5px] font-medium">
              {t("messageLabel")}
            </Label>
            <Textarea
              id="enq-message"
              data-testid="enquiry-message-input"
              rows={4}
              value={form.message}
              onChange={set("message")}
              placeholder={t("enquiryPlaceholder")}
              className="rounded-[10px] bg-card"
            />
          </div>

          <Button
            data-testid="enquiry-submit-button"
            type="submit"
            disabled={sending}
            className="h-12 w-full justify-center gap-2 rounded-[12px] bg-[hsl(var(--primary))] text-[15px] font-semibold text-primary-foreground hover:brightness-110"
          >
            {sending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Send className="h-[17px] w-[17px]" aria-hidden="true" />
            )}
            {t("sendEnquiry")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export default EnquiryDialog;
