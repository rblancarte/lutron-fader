class LutronFaderCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._fadeTime = 0;
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error('You need to define an entity');
    }
    this.config = config;
  }

  set hass(hass) {
    this._hass = hass;

    if (!this.content) {
      const card = document.createElement('ha-card');
      this.content = document.createElement('div');
      this.content.style.padding = '16px';
      card.appendChild(this.content);
      this.shadowRoot.appendChild(card);

      // Add styles
      const style = document.createElement('style');
      style.textContent = `
        ha-card {
          background: var(--ha-card-background, var(--card-background-color, white));
          border-radius: var(--ha-card-border-radius, 12px);
          box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,0.1));
        }
        .header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
        }
        .entity-name {
          font-size: 18px;
          font-weight: 500;
          color: var(--primary-text-color);
        }
        .state-badge {
          padding: 4px 12px;
          border-radius: 12px;
          font-size: 14px;
          font-weight: 500;
        }
        .state-badge.on {
          background: var(--primary-color);
          color: white;
        }
        .state-badge.off {
          background: var(--disabled-text-color);
          color: white;
        }
        .current-state {
          font-size: 14px;
          color: var(--secondary-text-color);
          margin-bottom: 16px;
        }
        .slider-container {
          margin-bottom: 16px;
        }
        .slider-label {
          font-size: 14px;
          color: var(--secondary-text-color);
          margin-bottom: 8px;
        }
        input[type="range"] {
          width: 100%;
          height: 40px;
          -webkit-appearance: none;
          appearance: none;
          background: transparent;
        }
        input[type="range"]::-webkit-slider-track {
          width: 100%;
          height: 8px;
          background: var(--primary-color);
          border-radius: 4px;
          opacity: 0.3;
        }
        input[type="range"]::-webkit-slider-thumb {
          -webkit-appearance: none;
          appearance: none;
          width: 24px;
          height: 24px;
          border-radius: 50%;
          background: var(--primary-color);
          cursor: pointer;
          margin-top: -8px;
        }
        input[type="range"]::-moz-range-track {
          width: 100%;
          height: 8px;
          background: var(--primary-color);
          border-radius: 4px;
          opacity: 0.3;
        }
        input[type="range"]::-moz-range-thumb {
          width: 24px;
          height: 24px;
          border-radius: 50%;
          background: var(--primary-color);
          cursor: pointer;
          border: none;
        }
        .fade-time-container {
          margin-bottom: 16px;
        }
        .fade-time-label {
          font-size: 14px;
          color: var(--secondary-text-color);
          margin-bottom: 8px;
        }
        input[type="number"] {
          width: 100%;
          padding: 12px;
          font-size: 16px;
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          background: var(--primary-background-color);
          color: var(--primary-text-color);
          box-sizing: border-box;
        }
        .button-container {
          display: flex;
          gap: 8px;
        }
        button {
          flex: 1;
          padding: 12px;
          font-size: 16px;
          font-weight: 500;
          border: none;
          border-radius: 8px;
          cursor: pointer;
          transition: background 0.2s;
        }
        .start-button {
          background: var(--primary-color);
          color: white;
        }
        .start-button:hover {
          opacity: 0.9;
        }
        .start-button:active {
          opacity: 0.8;
        }
        .off-button {
          background: var(--disabled-text-color);
          color: white;
        }
        .off-button:hover {
          opacity: 0.9;
        }
        .off-button:active {
          opacity: 0.8;
        }
        .brightness-display {
          text-align: center;
          font-size: 16px;
          color: var(--primary-text-color);
          margin-top: 4px;
        }
        .error {
          color: var(--error-color);
          font-size: 12px;
          margin-top: 4px;
        }
      `;
      this.shadowRoot.appendChild(style);
    }

    const entityId = this.config.entity;
    const stateObj = hass.states[entityId];

    if (!stateObj) {
      this.content.innerHTML = `<div class="error">Entity ${entityId} not found</div>`;
      return;
    }

    const isOn = stateObj.state === 'on';
    const brightness = stateObj.attributes.brightness || 0;
    const brightnessPercent = Math.round((brightness / 255) * 100);
    const name = this.config.name || stateObj.attributes.friendly_name || entityId;

    this.content.innerHTML = `
      <div class="header">
        <div class="entity-name">${name}</div>
        <div class="state-badge ${isOn ? 'on' : 'off'}">
          ${isOn ? 'ON' : 'OFF'}
        </div>
      </div>
      <div class="current-state">
        Current: ${isOn ? brightnessPercent + '%' : 'Off'}
      </div>
      <div class="slider-container">
        <div class="slider-label">Desired Brightness</div>
        <input type="range" min="0" max="100" value="${brightnessPercent}" id="brightness-slider">
        <div class="brightness-display"><span id="brightness-value">${brightnessPercent}</span>%</div>
      </div>
      <div class="fade-time-container">
        <div class="fade-time-label">Fade Time (seconds, 0-3600)</div>
        <input type="number" min="0" max="3600" value="${this._fadeTime}" id="fade-time-input" placeholder="Enter seconds (0-3600)">
        <div id="fade-time-error" class="error" style="display: none;"></div>
      </div>
      <div class="button-container">
        <button class="off-button" id="off-button">Turn Off</button>
        <button class="start-button" id="start-button">Start Fade</button>
      </div>
    `;

    // Add event listeners
    const slider = this.content.querySelector('#brightness-slider');
    const brightnessDisplay = this.content.querySelector('#brightness-value');
    const fadeTimeInput = this.content.querySelector('#fade-time-input');
    const fadeTimeError = this.content.querySelector('#fade-time-error');
    const startButton = this.content.querySelector('#start-button');
    const offButton = this.content.querySelector('#off-button');

    slider.addEventListener('input', (e) => {
      brightnessDisplay.textContent = e.target.value;
    });

    fadeTimeInput.addEventListener('input', (e) => {
      const value = parseInt(e.target.value);
      if (isNaN(value) || value < 0 || value > 3600) {
        fadeTimeError.textContent = 'Fade time must be between 0 and 3600 seconds';
        fadeTimeError.style.display = 'block';
      } else {
        fadeTimeError.style.display = 'none';
        this._fadeTime = value;
      }
    });

    startButton.addEventListener('click', () => {
      const brightness = parseInt(slider.value);
      const fadeTime = parseInt(fadeTimeInput.value) || 0;

      if (fadeTime < 0 || fadeTime > 3600) {
        fadeTimeError.textContent = 'Fade time must be between 0 and 3600 seconds';
        fadeTimeError.style.display = 'block';
        return;
      }

      fadeTimeError.style.display = 'none';

      // Call the light.turn_on service with transition
      this._hass.callService('light', 'turn_on', {
        entity_id: entityId,
        brightness_pct: brightness,
        transition: fadeTime
      });
    });

    offButton.addEventListener('click', () => {
      const fadeTime = parseInt(fadeTimeInput.value) || 0;

      if (fadeTime < 0 || fadeTime > 3600) {
        fadeTimeError.textContent = 'Fade time must be between 0 and 3600 seconds';
        fadeTimeError.style.display = 'block';
        return;
      }

      fadeTimeError.style.display = 'none';

      // Call the light.turn_off service with transition
      this._hass.callService('light', 'turn_off', {
        entity_id: entityId,
        transition: fadeTime
      });
    });
  }

  getCardSize() {
    return 4;
  }
}

customElements.define('lutron-fader-card', LutronFaderCard);

// Add the card to the custom card registry
window.customCards = window.customCards || [];
window.customCards.push({
  type: 'lutron-fader-card',
  name: 'Lutron Fader Card',
  description: 'A custom card for controlling Lutron lights with fade time',
  preview: false,
});

console.info(
  '%c LUTRON-FADER-CARD %c Version 0.9.0 ',
  'color: white; background: #039be5; font-weight: 700;',
  'color: #039be5; background: white; font-weight: 700;'
);
