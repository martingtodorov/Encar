import { Search, Heart, Bookmark, Ship, Package, HelpCircle } from "lucide-react";
import { useApp } from "@/context/AppContext";
import { useAuth } from "@/context/AuthContext";

/**
 * The one list of navigation destinations, shared by the desktop bar and the mobile drawer.
 *
 * Two hand-maintained copies of a menu drift apart within a week — this is why the phone was
 * showing a different set of links from the desktop. Both now render from here, so a change
 * lands in both at once. "My purchases" only exists for a signed-in buyer; everything else is
 * public, including the tracker.
 */
export function useNavItems() {
  const { t, favourites, searches } = useApp();
  const { user } = useAuth();

  return [
    { to: "/", label: t("navSearch"), icon: Search },
    { to: "/saved", label: t("savedCars"), icon: Heart, count: favourites.length },
    { to: "/searches", label: t("savedSearches"), icon: Bookmark, count: searches.length },
    { to: "/track", label: t("navTrack"), icon: Ship },
    ...(user ? [{ to: "/purchases", label: t("navPurchases"), icon: Package }] : []),
    { to: "/how-it-works", label: t("navHowItWorks"), icon: HelpCircle },
  ];
}

export default useNavItems;
