import { describe, expect, it } from 'vitest';
import { retainChipletNames } from './MapChildrenEditor';

const blocks = [{ id: 'B1', name: 'Top Test' }, { id: 'B2', name: 'Bottom Test' }, { id: 'B3', name: 'Other Block' }];

describe('chiplet block selection', () => {
  it('preserves edited names by block when other blocks are added or removed', () => {
    expect(retainChipletNames(
      blocks, ['B1', 'B2'], ['EDITED_CHIPLET', 'WAFER_Bottom_Test'], ['B3', 'B1'], 'WAFER',
    )).toEqual(['EDITED_CHIPLET', 'WAFER_Other_Block']);
  });

  it('uses the complete reviewed block order and preserves an edited blank name for validation', () => {
    expect(retainChipletNames(blocks, ['B1'], [''], ['B2', 'B1'], 'WAFER'))
      .toEqual(['', 'WAFER_Bottom_Test']);
  });
});
