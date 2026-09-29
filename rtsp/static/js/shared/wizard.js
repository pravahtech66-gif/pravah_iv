import { S } from './state.js';
import { drawSnapshotToCanvas } from './canvas.js';
import { redrawAoiOverlay, updateAoiReadout } from './aoi.js';
import { updateHaDisplay } from './config.js';

export const PROG_MAP  = {1:0, 2:30, '4a':55, '4b':70, '4c':88, 6:100};
export const LABEL_MAP = {1:'', 2:'Step 1 of 3',
                   '4a':'Step 2 of 3', '4b':'Step 2 of 3', '4c':'Step 3 of 3',
                   6:'Live stream'};

export function makeShowStep(onEnter) {
  return function showStep(n) {
    document.querySelectorAll('.step').forEach(el => el.classList.remove('active'));
    const el = document.getElementById('step' + n);
    if (el) el.classList.add('active');
    S.currentStep = n;
    const fill = document.getElementById('progressFill');
    const pill = document.getElementById('stepPill');
    fill.style.width = (PROG_MAP[n] || 0) + '%';
    if (n === 6) {
      pill.textContent = 'Live stream';
      document.getElementById('stepInfo').style.display = 'none';
    } else {
      pill.textContent = LABEL_MAP[n] || '';
    }
    if (onEnter) onEnter(n);
    if (n === '4c') {
      requestAnimationFrame(() => {
        if (S.videoLoaded) {
          drawSnapshotToCanvas(
            document.getElementById('frameCanvas4c'),
            document.getElementById('frameContainer4c')
          );
        }
        redrawAoiOverlay();
        updateAoiReadout();
      });
    }
    if (n === '4b') updateHaDisplay();
    window.scrollTo(0, 0);
  };
}
