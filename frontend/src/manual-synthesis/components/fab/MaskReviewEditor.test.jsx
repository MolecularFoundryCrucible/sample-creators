import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import FabTraveler from './FabTraveler';
import { ingestionIsWaiting } from './MaskReviewEditor';

const userInfo = { orcid: '0000-0001', name: 'Test', projects: ['QCMF_TEST'], selectedProject: 'QCMF_TEST' };

describe('mask design routes', () => {
  it('opens the mask list on a direct /fabrication/masks/ load without an id', () => {
    const html = renderToStaticMarkup(<FabTraveler userInfo={userInfo} initialMaskView />);
    expect(html).toContain('Upload GDS');
    expect(html).not.toContain('+ New wafer');
  });
});

describe('GDS ingestion status', () => {
  it.each(['file not found', 'not supported', 'not_supported', 'failed', 'cancelled'])(
    'stops polling after terminal %s status without geometry', (status) => {
      expect(ingestionIsWaiting(null, [{ status }])).toBe(false);
    },
  );

  it('polls while pending and stops once geometry arrives', () => {
    expect(ingestionIsWaiting(null, [{ status: 'requested' }])).toBe(true);
    expect(ingestionIsWaiting(null, [])).toBe(true);
    expect(ingestionIsWaiting({ shapes: [] }, [{ status: 'requested' }])).toBe(false);
  });
});
