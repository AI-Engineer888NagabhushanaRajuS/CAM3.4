import {
  Key,
  Lightning,
  Info,
  GearSix,
  Buildings,
  UsersThree,
  CurrencyDollar,
} from '@phosphor-icons/react';

export type SettingsTabId =
  | 'providers'
  | 'skills'
  | 'projectTracking'
  | 'currencies'
  | 'users'
  | 'general'
  | 'about';

export const SETTINGS_TABS = [
  { id: 'providers' as const, labelKey: 'tabs.providers', icon: Key },
  { id: 'skills' as const, labelKey: 'tabs.skills', icon: Lightning },
  { id: 'projectTracking' as const, labelKey: 'tabs.projectTracking', icon: Buildings },
  // Admin-only -- filtered out for non-admin sessions in SettingsDialog.tsx.
  { id: 'currencies' as const, labelKey: 'tabs.currencies', icon: CurrencyDollar },
  { id: 'users' as const, labelKey: 'tabs.users', icon: UsersThree },
  { id: 'general' as const, labelKey: 'tabs.general', icon: GearSix },
  { id: 'about' as const, labelKey: 'tabs.about', icon: Info },
] as const;

/** First 4 providers shown in collapsed view (matches PROVIDER_ORDER in ProviderGrid). */
export const FIRST_FOUR_PROVIDERS = ['openai', 'anthropic', 'google', 'bedrock'] as const;
