import { useTranslation } from 'react-i18next';
import {
  PRODUCT_CLIENT,
  PRODUCT_NAME,
  PRODUCT_VERSION,
  isRealBuildVersion,
} from '@/lib/productVersion';

interface AboutTabProps {
  appVersion: string;
}

export function AboutTab({ appVersion }: AboutTabProps) {
  const { t } = useTranslation('settings');
  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-border bg-card p-6">
        <div className="space-y-4">
          <div>
            <div className="text-lg font-semibold">
              {PRODUCT_NAME} (for {PRODUCT_CLIENT})
            </div>
            <p className="mt-1 text-sm text-muted-foreground">{t('about.description')}</p>
          </div>
          <div>
            <div className="text-sm text-muted-foreground">{t('about.panesTitle')}</div>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm">
              <li>{t('about.paneLeft')}</li>
              <li>{t('about.paneMiddle')}</li>
              <li>{t('about.paneRight')}</li>
            </ul>
          </div>
          <div>
            <div className="text-sm text-muted-foreground">{t('about.visitUs')}</div>
            <a
              href="https://digibull.ai/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary hover:underline"
            >
              digibull.ai
            </a>
          </div>
          <div>
            <div className="text-sm text-muted-foreground">{t('about.haveQuestion')}</div>
            <a href="mailto:solutions@digibull.ai" className="text-primary hover:underline">
              solutions@digibull.ai
            </a>
          </div>
          <div>
            <div className="text-sm text-muted-foreground">{t('about.versionLabel')}</div>
            <div className="font-medium">{PRODUCT_VERSION}</div>
          </div>
          {isRealBuildVersion(appVersion) && (
            <div>
              <div className="text-sm text-muted-foreground">{t('about.buildLabel')}</div>
              <div className="font-medium">{appVersion}</div>
            </div>
          )}
          <div>
            <div className="text-sm text-muted-foreground">{t('about.developedBy')}</div>
            <div className="font-medium">DigiBull Team</div>
          </div>
        </div>
        <div className="mt-6 pt-4 border-t border-border text-xs text-muted-foreground">
          {t('about.allRightsReserved')}
        </div>
      </div>
    </div>
  );
}
