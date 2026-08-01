{
  "brand": {
    "name": "Encar Import (localized skin)",
    "attributes": [
      "trust-first",
      "price-transparent",
      "high-density scanning",
      "mobile-native",
      "documentation-forward"
    ],
    "north_star": "Make buyers feel safe importing a real car from Korea by surfacing verified documentation and a final landed price in their currency—fast."
  },
  "design_personality": {
    "style_fusion": [
      "Swiss-style information hierarchy (dense, aligned, scannable)",
      "Warm showroom neutrals (sand/ivory surfaces) + disciplined ocean-blue actions",
      "Bento-like card grid with strong price typography",
      "Documentation UI cues (stamps, chips, ‘verified’ patterns) without skeuomorphism"
    ],
    "do_not": [
      "No transparent backgrounds anywhere",
      "No dark-mode requirement; keep default light theme",
      "No purple for AI/chat vibes",
      "No text-heavy gradients",
      "No centered app container"
    ]
  },
  "tokens": {
    "css_custom_properties": {
      "note": "Implement by replacing :root tokens in /frontend/src/index.css (HSL values) OR add a second token layer. Keep shadcn variable names for compatibility.",
      "colors_hex": {
        "bg": "#F6F1E8",
        "surface": "#FFFFFF",
        "surface_2": "#FBF8F2",
        "text": "#121417",
        "text_muted": "#5B6673",
        "border": "#E6DED2",
        "primary": "#0B4F6C",
        "primary_hover": "#09445D",
        "primary_soft": "#E6F2F7",
        "accent": "#0E7C86",
        "accent_soft": "#E3F6F5",
        "warning": "#B45309",
        "warning_soft": "#FFF3D6",
        "success": "#0F766E",
        "success_soft": "#DFF7F4",
        "danger": "#B42318",
        "danger_soft": "#FFE4E1",
        "focus_ring": "#2B8DBA",
        "link": "#0B4F6C",
        "chip_bg": "#F1E9DD"
      },
      "shadows": {
        "shadow_sm": "0 1px 2px rgba(18,20,23,0.06)",
        "shadow_md": "0 10px 24px rgba(18,20,23,0.10)",
        "shadow_lift": "0 14px 34px rgba(18,20,23,0.14)"
      },
      "radius": {
        "radius_sm": "10px",
        "radius_md": "14px",
        "radius_lg": "18px",
        "radius_xl": "22px"
      },
      "spacing": {
        "grid_gutter": "24px",
        "section_py": "56px",
        "card_p": "14px",
        "control_h": "44px"
      }
    },
    "gradients": {
      "allowed_usage": [
        "Hero background only (max ~18% viewport height)",
        "Decorative top border line / subtle overlay"
      ],
      "hero_background": "linear-gradient(135deg, #F6F1E8 0%, #EAF4F8 55%, #F6F1E8 100%)",
      "restriction": "Follow GRADIENT RESTRICTION RULE (no saturated/dark gradients; no gradients on small elements)."
    },
    "texture": {
      "noise_overlay": {
        "usage": "Optional subtle noise on hero only to avoid flatness.",
        "css": "background-image: radial-gradient(rgba(18,20,23,0.035) 1px, transparent 1px); background-size: 3px 3px;"
      }
    }
  },
  "typography": {
    "font_selection": {
      "primary": {
        "name": "IBM Plex Sans",
        "why": "Excellent Cyrillic coverage + utilitarian trust tone for dense filters and specs.",
        "fallback_stack": "'IBM Plex Sans', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, Arial, 'Noto Sans', 'Liberation Sans', sans-serif"
      },
      "numeric": {
        "name": "IBM Plex Sans",
        "note": "Use tabular numbers for prices and mileage where possible (Tailwind: tabular-nums)."
      }
    },
    "scale": {
      "h1": "text-4xl sm:text-5xl lg:text-6xl",
      "h2": "text-base md:text-lg",
      "body": "text-sm sm:text-base",
      "small": "text-xs sm:text-sm"
    },
    "price_typography": {
      "card_price": "text-xl sm:text-2xl font-semibold tracking-tight tabular-nums",
      "detail_price": "text-3xl sm:text-4xl font-semibold tracking-tight tabular-nums",
      "formatting": {
        "rule": "Always locale-format with Intl.NumberFormat for BG/RO/EN and currency switcher (EUR/BGN/RON).",
        "examples": {
          "bg": "12 499 €",
          "ro": "12.499 €",
          "en": "€12,499"
        }
      }
    },
    "text_overflow_rules": {
      "labels": "Never hard-truncate critical filter labels. Allow wrapping to 2 lines in filter rows (leading-tight).",
      "chips": "Applied-filter chips may truncate with ellipsis after ~22–26ch; show full value on hover tooltip (desktop) / long-press (mobile).",
      "card_title": "Clamp to 2 lines (line-clamp-2) to handle BG/RO expansion."
    }
  },
  "layout": {
    "grid_system": {
      "container": "max-w-[1280px] mx-auto px-4 sm:px-6",
      "desktop_columns": "12-col mental model",
      "landing_split": {
        "desktop": "Filters 320–360px fixed column + results fluid",
        "tablet": "Filters collapsible (Sheet) + results full width",
        "mobile": "Top search + sticky filter/sort bar; filters in full-height Sheet"
      }
    },
    "header": {
      "height": "64px",
      "structure": [
        "Left: logo + tagline (optional)",
        "Center (desktop): search input",
        "Right: language switcher + currency switcher + favourites"
      ],
      "mobile": [
        "Row 1: logo + language/currency",
        "Row 2: search input full width",
        "Row 3: sticky controls (Filter, Sort, Saved)"
      ]
    },
    "hero": {
      "height": "~280–360px desktop, ~220px mobile",
      "content": [
        "H1: ‘Внос на автомобили от Корея с крайна цена’ (localized)",
        "H2: trust line: ‘Крайна цена с мита/ДДС/транспорт. Документи от Encar.’",
        "3 trust bullets as chips: ‘Проверена история’, ‘Инспекция’, ‘Застрахователни записи’",
        "Primary CTA: ‘Започни търсене’ scrolls to results"
      ]
    }
  },
  "components": {
    "component_path": {
      "shadcn_primary": [
        "/app/frontend/src/components/ui/button.jsx",
        "/app/frontend/src/components/ui/input.jsx",
        "/app/frontend/src/components/ui/select.jsx",
        "/app/frontend/src/components/ui/slider.jsx",
        "/app/frontend/src/components/ui/badge.jsx",
        "/app/frontend/src/components/ui/card.jsx",
        "/app/frontend/src/components/ui/sheet.jsx",
        "/app/frontend/src/components/ui/drawer.jsx",
        "/app/frontend/src/components/ui/accordion.jsx",
        "/app/frontend/src/components/ui/collapsible.jsx",
        "/app/frontend/src/components/ui/scroll-area.jsx",
        "/app/frontend/src/components/ui/pagination.jsx",
        "/app/frontend/src/components/ui/skeleton.jsx",
        "/app/frontend/src/components/ui/tooltip.jsx",
        "/app/frontend/src/components/ui/tabs.jsx",
        "/app/frontend/src/components/ui/separator.jsx",
        "/app/frontend/src/components/ui/sonner.jsx"
      ],
      "recommended_new_components_js": [
        "src/components/HeaderBar.js",
        "src/components/LanguageCurrencySwitchers.js",
        "src/components/SearchBar.js",
        "src/components/FilterSidebar.js",
        "src/components/FilterSheetMobile.js",
        "src/components/AppliedFiltersChips.js",
        "src/components/SortControl.js",
        "src/components/CarCard.js",
        "src/components/CarGrid.js",
        "src/components/CarCardSkeleton.js",
        "src/components/ImageWithFallback.js",
        "src/components/TrustStrip.js"
      ]
    },
    "header_controls": {
      "language_switcher": {
        "pattern": "DropdownMenu with 3 options BG/RO/EN; show current as compact pill.",
        "tailwind": "h-9 rounded-full border bg-white px-3 text-sm",
        "data_testid": "language-switcher"
      },
      "currency_switcher": {
        "pattern": "DropdownMenu with EUR/BGN/RON; show symbol + code.",
        "data_testid": "currency-switcher"
      },
      "favourites": {
        "pattern": "Button variant=ghost with heart icon + count badge",
        "data_testid": "header-favourites-button"
      }
    },
    "filter_sidebar": {
      "desktop": {
        "container": "sticky top-[76px] h-[calc(100vh-88px)]",
        "surface": "bg-white border rounded-[14px] shadow-[var(--shadow-sm)]",
        "scroll": "ScrollArea for long filter lists",
        "sections": [
          "Make/Model (Command searchable)",
          "Year range (two Inputs or Slider + Inputs)",
          "Price range (Slider + Inputs; currency-aware)",
          "Mileage range (Slider + Inputs)",
          "Fuel type (Checkbox group)",
          "Transmission (Checkbox group)",
          "Body type (ToggleGroup or Checkbox)",
          "Korean region (Select)",
          "Trust toggles: accident-free, has-inspection-report, has-insurance-record, Encar-diagnosed"
        ],
        "apply_behavior": "Instant filtering (debounced 250–350ms) + immediate result count update.",
        "reset": {
          "ui": "Secondary button ‘Изчисти’ pinned at bottom",
          "data_testid": "filters-reset-button"
        }
      },
      "mobile": {
        "pattern": "Sheet (right) or Drawer (bottom) full-height with sticky footer actions",
        "open_button": {
          "label": "Филтри",
          "data_testid": "open-filters-button"
        },
        "footer": [
          "Primary: ‘Покажи резултати (N)’",
          "Secondary: ‘Изчисти’"
        ]
      },
      "control_specs": {
        "control_height": "h-11",
        "label": "text-sm font-medium text-[#1B2430]",
        "help_text": "text-xs text-[#5B6673]",
        "focus": "focus-visible:ring-2 focus-visible:ring-[--focus_ring] focus-visible:ring-offset-2"
      }
    },
    "applied_filters_chips": {
      "pattern": "Horizontal ScrollArea of removable chips under the sticky control bar",
      "chip": "inline-flex items-center gap-2 rounded-full bg-[--chip_bg] px-3 py-1 text-sm",
      "remove": "Button variant=ghost size=icon",
      "data_testid": "applied-filters"
    },
    "sort_control": {
      "pattern": "Select with options newest, price asc/desc, mileage asc, year desc",
      "placement": "Right side of results header (desktop) / in sticky bar (mobile)",
      "data_testid": "sort-control"
    },
    "result_count_pagination": {
      "result_count": {
        "style": "text-sm text-muted-foreground",
        "data_testid": "result-count"
      },
      "pagination": {
        "component": "shadcn Pagination",
        "deep_pagination": "Add ‘Jump to page’ Input + Go button for large datasets",
        "data_testid": "pagination"
      }
    },
    "car_card": {
      "surface": "bg-white border rounded-[18px] shadow-[var(--shadow-sm)] hover:shadow-[var(--shadow-md)]",
      "layout": [
        "Top: image area with fixed aspect ratio",
        "Middle: title + key specs row",
        "Bottom: price + trust badges + save button"
      ],
      "image_handling": {
        "container": "AspectRatio ratio={4/3} (desktop) and 1/1 (mobile grid) optional",
        "img": "object-cover w-full h-full",
        "loading": "Skeleton overlay + subtle shimmer",
        "error": "Fallback panel with car icon + ‘Снимката не е налична’",
        "slow": "Show ‘Зареждане…’ micro label after 800ms",
        "data_testid": "car-card-image"
      },
      "badges": {
        "max": 3,
        "types": {
          "diagnosed": "Badge bg=[--accent_soft] text=[--accent]",
          "inspected": "Badge bg=[--primary_soft] text=[--primary]",
          "accident_free": "Badge bg=[--success_soft] text=[--success]"
        },
        "overflow": "If more than 3, show ‘+N’ badge with Tooltip listing all"
      },
      "save": {
        "ui": "Top-right icon button over image (solid white background, not transparent)",
        "data_testid": "car-card-save-button"
      },
      "cta": {
        "ui": "Whole card clickable + secondary ‘Виж детайли’ button on hover (desktop) / always visible on mobile",
        "data_testid": "car-card-open"
      },
      "price": {
        "style": "text-xl sm:text-2xl font-semibold tabular-nums text-[#121417]",
        "sub": "text-xs text-muted-foreground ‘Крайна цена’",
        "data_testid": "car-card-price"
      },
      "spec_row": {
        "items": ["year", "mileage", "fuel", "transmission"],
        "style": "text-xs sm:text-sm text-[#5B6673] flex flex-wrap gap-x-3 gap-y-1"
      }
    },
    "trust_strip": {
      "purpose": "Reduce suspicion: explain final landed price + documentation.",
      "placement": "Between hero and results OR above grid as a compact strip",
      "layout": "3 cards in a row desktop, stacked mobile",
      "items": [
        {
          "title": "Крайна цена",
          "body": "Мита, ДДС и транспорт са включени. Без изненади.",
          "data_testid": "trust-strip-final-price"
        },
        {
          "title": "Документи",
          "body": "Инспекция и застрахователна история от Encar.",
          "data_testid": "trust-strip-docs"
        },
        {
          "title": "Бързо търсене",
          "body": "Филтрите обновяват резултатите моментално.",
          "data_testid": "trust-strip-fast-search"
        }
      ]
    }
  },
  "states": {
    "loading": {
      "grid": "Show 12–24 CarCardSkeletons; keep layout stable.",
      "filters": "Disable apply buttons; show inline spinner next to result count.",
      "data_testid": "loading-state"
    },
    "empty": {
      "message": "No results with current filters; suggest removing 1–2 filters.",
      "actions": ["Clear filters", "Broaden year/price"],
      "data_testid": "empty-state"
    },
    "error": {
      "pattern": "Inline Alert at top of results + retry button",
      "data_testid": "error-state"
    },
    "image_error": {
      "pattern": "Fallback tile with neutral illustration + retry image button",
      "data_testid": "image-fallback"
    }
  },
  "motion": {
    "principles": [
      "Fast, subtle, functional (trust apps should not feel gimmicky)",
      "Prefer opacity/translate micro transitions; avoid large bouncy motion"
    ],
    "micro_interactions": {
      "buttons": "hover: brightness-95; active: scale-[0.98]; focus ring visible",
      "cards": "hover elevates shadow + slight translate-y-0.5 (desktop only)",
      "filter_changes": "Result count animates with a quick fade (150ms) when updated",
      "saved": "Heart icon fills + toast via sonner (‘Запазено’)"
    },
    "libraries": {
      "optional": {
        "framer_motion": {
          "why": "Entrance animations for cards + sheet transitions; keep minimal.",
          "install": "npm i framer-motion",
          "usage": "AnimatePresence for grid updates; reduce motion when prefers-reduced-motion."
        }
      }
    }
  },
  "accessibility": {
    "wcag": "AA minimum",
    "focus": "Use focus-visible rings on all interactive controls; never remove outline without replacement.",
    "keyboard": [
      "Filters navigable via Tab",
      "Accordion sections open via Enter/Space",
      "Applied filter chips removable via keyboard"
    ],
    "touch": "Minimum 44px hit targets (control height token).",
    "aria": [
      "Add aria-labels for icon-only buttons (save, close sheet)",
      "Announce result count changes with aria-live=polite"
    ]
  },
  "performance": {
    "images": {
      "rules": [
        "Use loading=lazy on grid images",
        "Use decoding=async",
        "Use fixed aspect-ratio containers to prevent layout shift",
        "Use IntersectionObserver to delay image src assignment until near viewport (optional)"
      ]
    },
    "lists": {
      "rule": "Consider windowing for 48-card pages on low-end devices (react-window) if needed.",
      "optional_install": "npm i react-window"
    },
    "filtering": {
      "rule": "Debounce network calls 250–350ms; keep UI responsive with optimistic skeletons."
    }
  },
  "images": {
    "image_urls": [
      {
        "category": "hero_background",
        "description": "Showroom exterior / modern dealership vibe (use as subtle hero background image with low opacity overlay).",
        "url": "https://images.unsplash.com/photo-1593019856611-7ef1b2226a8b?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NTY2NzZ8MHwxfHNlYXJjaHwzfHxtb2Rlcm4lMjBjYXIlMjBzaG93cm9vbSUyMGV4dGVyaW9yJTIwZGF5bGlnaHR8ZW58MHx8fGJsdWV8MTc4NTYyMzMzNHww&ixlib=rb-4.1.0&q=85"
      },
      {
        "category": "hero_secondary",
        "description": "Alternative hero image option (clean exterior).",
        "url": "https://images.unsplash.com/photo-1569781195388-04bfbc91506d?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NTY2NzZ8MHwxfHNlYXJjaHwyfHxtb2Rlcm4lMjBjYXIlMjBzaG93cm9vbSUyMGV4dGVyaW9yJTIwZGF5bGlnaHR8ZW58MHx8fGJsdWV8MTc4NTYyMzMzNHww&ixlib=rb-4.1.0&q=85"
      },
      {
        "category": "trust_docs_section",
        "description": "Documentation vibe image for trust section (use small, not as background; keep under 20% viewport).",
        "url": "https://images.unsplash.com/photo-1708920325932-a4bda5f03e46?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NDk1ODF8MHwxfHNlYXJjaHwxfHxjYXIlMjBpbnNwZWN0aW9uJTIwZG9jdW1lbnQlMjBwYXBlcndvcmt8ZW58MHx8fGJsYWNrX2FuZF93aGl0ZXwxNzg1NjIzMzQ2fDA&ixlib=rb-4.1.0&q=85"
      },
      {
        "category": "detail_page_gallery_placeholder",
        "description": "Fallback/placeholder vibe for when Encar images fail (do not show people; use neutral).",
        "url": "https://images.unsplash.com/photo-1477699971141-3be31dc410ec?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NTY2NzZ8MHwxfHNlYXJjaHwxfHxtb2Rlcm4lMjBjYXIlMjBzaG93cm9vbSUyMGV4dGVyaW9yJTIwZGF5bGlnaHR8ZW58MHx8fGJsdWV8MTc4NTYyMzMzNHww&ixlib=rb-4.1.0&q=85"
      }
    ]
  },
  "instructions_to_main_agent": {
    "landing_page_priority": [
      "Build a mobile-first landing/search page with: HeaderBar (language/currency), SearchBar, sticky Filter/Sort bar, AppliedFiltersChips, CarGrid + Pagination.",
      "Desktop: show FilterSidebar as sticky left column; Mobile: use Sheet/Drawer for filters.",
      "Ensure every interactive element and key info has data-testid (kebab-case).",
      "Implement robust image loading: AspectRatio + Skeleton + fallback state; never allow layout shift.",
      "Use IBM Plex Sans via Google Fonts (include Cyrillic subset) and apply tabular-nums to price/mileage.",
      "Replace default CRA App.css centered header styles; do not center the app container.",
      "Keep gradients limited to hero background only (<20% viewport)."
    ],
    "tailwind_class_recipes": {
      "page_bg": "bg-[#F6F1E8] text-[#121417]",
      "surface_card": "bg-white border border-[#E6DED2] rounded-[18px] shadow-[0_1px_2px_rgba(18,20,23,0.06)]",
      "primary_button": "bg-[#0B4F6C] text-white hover:bg-[#09445D] focus-visible:ring-2 focus-visible:ring-[#2B8DBA] focus-visible:ring-offset-2",
      "secondary_button": "bg-[#E6F2F7] text-[#0B4F6C] hover:bg-[#D7ECF4]",
      "chip": "bg-[#F1E9DD] text-[#1B2430]",
      "badge_success": "bg-[#DFF7F4] text-[#0F766E]",
      "badge_info": "bg-[#E6F2F7] text-[#0B4F6C]",
      "badge_accent": "bg-[#E3F6F5] text-[#0E7C86]"
    },
    "js_only_note": "Project uses .js (not .tsx). Keep components in JS, use prop-types optionally, and keep shadcn imports consistent."
  },
  "appendix_general_ui_ux_design_guidelines": "<General UI UX Design Guidelines>\n    - You must **not** apply universal transition. Eg: `transition: all`. This results in breaking transforms. Always add transitions for specific interactive elements like button, input excluding transforms\n    - You must **not** center align the app container, ie do not add `.App { text-align: center; }` in the css file. This disrupts the human natural reading flow of text\n   - NEVER: use AI assistant Emoji characters like`🤖🧠💭💡🔮🎯📚🎭🎬🎪🎉🎊🎁🎀🎂🍰🎈🎨🎰💰💵💳🏦💎🪙💸🤑📊📈📉💹🔢🏆🥇 etc for icons. Always use **FontAwesome cdn** or **lucid-react** library already installed in the package.json\n\n **GRADIENT RESTRICTION RULE**\nNEVER use dark/saturated gradient combos (e.g., purple/pink) on any UI element.  Prohibited gradients: blue-500 to purple 600, purple 500 to pink-500, green-500 to blue-500, red to pink etc\nNEVER use dark gradients for logo, testimonial, footer etc\nNEVER let gradients cover more than 20% of the viewport.\nNEVER apply gradients to text-heavy content or reading areas.\nNEVER use gradients on small UI elements (<100px width).\nNEVER stack multiple gradient layers in the same viewport.\n\n**ENFORCEMENT RULE:**\n    • Id gradient area exceeds 20% of viewport OR affects readability, **THEN** use solid colors\n\n**How and where to use:**\n   • Section backgrounds (not content backgrounds)\n   • Hero section header content. Eg: dark to light to dark color\n   • Decorative overlays and accent elements only\n   • Hero section with 2-3 mild color\n   • Gradients creation can be done for any angle say horizontal, vertical or diagonal\n\n- For AI chat, voice application, **do not use purple color. Use color like light green, ocean blue, peach orange etc**\n\n</Font Guidelines>\n\n- Every interaction needs micro-animations - hover states, transitions, parallax effects, and entrance animations. Static = dead. \n   \n- Use 2-3x more spacing than feels comfortable. Cramped designs look cheap.\n\n- Subtle grain textures, noise overlays, custom cursors, selection states, and loading animations: separates good from extraordinary.\n   \n- Before generating UI, infer the visual style from the problem statement (palette, contrast, mood, motion) and immediately instantiate it by setting global design tokens (primary, secondary/accent, background, foreground, ring, state colors), rather than relying on any library defaults. Don't make the background dark as a default step, always understand problem first and define colors accordingly\n    Eg: - if it implies playful/energetic, choose a colorful scheme\n           - if it implies monochrome/minimal, choose a black–white/neutral scheme\n\n**Component Reuse:**\n\t- Prioritize using pre-existing components from src/components/ui when applicable\n\t- Create new components that match the style and conventions of existing components when needed\n\t- Examine existing components to understand the project's component patterns before creating new ones\n\n**IMPORTANT**: Do not use HTML based component like dropdown, calendar, toast etc. You **MUST** always use `/app/frontend/src/components/ui/ ` only as a primary components as these are modern and stylish component\n\n**Best Practices:**\n\t- Use Shadcn/UI as the primary component library for consistency and accessibility\n\t- Import path: ./components/[component-name]\n\n**Export Conventions:**\n\t- Components MUST use named exports (export const ComponentName = ...)\n\t- Pages MUST use default exports (export default function PageName() {...})\n\n**Toasts:**\n  - Use `sonner` for toasts\"\n  - Sonner component are located in `/app/src/components/ui/sonner.tsx`\n\nUse 2–4 color gradients, subtle textures/noise overlays, or CSS-based noise to avoid flat visuals.\n</General UI UX Design Guidelines>"
}
