import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import FabTraveler from './FabTraveler';
import MainForm from '../MainForm';
import { ingestionIsWaiting } from './MaskReviewEditor';

const userInfo = { orcid: '0000-0001', name: 'Test', projects: ['QCMF_TEST'], selectedProject: 'QCMF_TEST' };

describe('project picker and user banner consolidation', () => {
  it('FabTraveler does not render fab-project or Current User banner and renders tabs for selected project', () => {
    const html = renderToStaticMarkup(<FabTraveler userInfo={userInfo} />);
    expect(html).not.toContain('fab-project');
    expect(html).not.toContain('Current User:');
    expect(html).toContain('Wafers');
    expect(html).toContain('Mask designs');
  });

  it('FabTraveler shows project prompt when no project is selected', () => {
    const noProjUser = { ...userInfo, selectedProject: '', projects: [] };
    const html = renderToStaticMarkup(<FabTraveler userInfo={noProjUser} />);
    expect(html).toContain('Select a project above to view wafers and mask designs.');
  });

  it('MainForm does not render synthesis-project or Current User banner and renders synthesis controls', () => {
    const html = renderToStaticMarkup(<MainForm userInfo={userInfo} />);
    expect(html).not.toContain('synthesis-project');
    expect(html).not.toContain('Current User:');
    expect(html).toContain('Synthesis Category');
    expect(html).toContain('Synthesis Type');
  });

  it('MainForm shows project prompt when no project is selected', () => {
    const noProjUser = { ...userInfo, selectedProject: '', projects: [] };
    const html = renderToStaticMarkup(<MainForm userInfo={noProjUser} />);
    expect(html).toContain('Select a project above to enter synthesis data.');
  });
});

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
