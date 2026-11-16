/** Single source of truth for the product name/version shown to users (About page, etc.). */
export const PRODUCT_NAME = 'CAM4';
export const PRODUCT_CLIENT = 'Centum';
export const PRODUCT_VERSION = '4';

/** Browser/dev builds report a placeholder such as "0.0.0-browser"; that is not a real build. */
export function isRealBuildVersion(version: string): boolean {
  return version !== '' && !version.startsWith('0.0.0');
}
