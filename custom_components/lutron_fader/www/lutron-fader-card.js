class LutronFaderCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._fadeTime = 0;
    this._initialized = false;
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error('You need to define an entity');
    }
    this.config = config;
  }

  set hass(hass) {
    this._hass = hass;

    const entityId = this.config.entity;
    const stateObj = hass.states[entityId];

    if (!this._initialized) {
      this._buildCard(stateObj);
      this._initialized = true;
    }

    this._updateState(stateObj);
  }

  _buildCard(stateObj) {
    const card = document.createElement('ha-card');
    this.content = document.createElement('div');
    this.content.style.padding = '16px';
    card.appendChild(this.content);
    this.shadowRoot.appendChild(card);

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
      .time-input-row {
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .time-input-row input[type="number"] {
        flex: 1;
        text-align: center;
        padding: 12px 4px;
      }
      .time-input-row .time-sep {
        font-size: 20px;
        font-weight: 500;
        color: var(--primary-text-color);
      }
      .time-input-row .time-unit {
        font-size: 11px;
        color: var(--secondary-text-color);
        text-align: center;
        margin-top: 2px;
      }
      .time-field {
        display: flex;
        flex-direction: column;
        flex: 1;
      }
    `;
    this.shadowRoot.appendChild(style);

    const entityId = this.config.entity;
    const isOn = stateObj && stateObj.state === 'on';
    const brightness = stateObj && stateObj.attributes.brightness || 0;
    const brightnessPercent = Math.round((brightness / 255) * 100);
    const name = this.config.name || (stateObj && stateObj.attributes.friendly_name) || entityId;

    this.content.innerHTML = `
      <div class="header">
        <div class="entity-name">${name}</div>
        <div class="state-badge ${isOn ? 'on' : 'off'}" id="state-badge">
          ${isOn ? 'ON' : 'OFF'}
        </div>
      </div>
      <div class="current-state" id="current-state">
        Current: ${isOn ? brightnessPercent + '%' : 'Off'}
      </div>
      <div class="slider-container">
        <div class="slider-label">Desired Brightness</div>
        <input type="range" min="0" max="100" value="${brightnessPercent}" id="brightness-slider">
        <div class="brightness-display"><span id="brightness-value">${brightnessPercent}</span>%</div>
      </div>
      <div class="fade-time-container">
        <div class="fade-time-label">Fade Time (max 4 hours)</div>
        <div class="time-input-row">
          <div class="time-field">
            <input type="number" min="0" max="4" value="0" id="fade-hours" placeholder="0">
            <div class="time-unit">HH</div>
          </div>
          <span class="time-sep">:</span>
          <div class="time-field">
            <input type="number" min="0" max="59" value="0" id="fade-minutes" placeholder="0">
            <div class="time-unit">MM</div>
          </div>
          <span class="time-sep">:</span>
          <div class="time-field">
            <input type="number" min="0" max="59" value="0" id="fade-seconds" placeholder="0">
            <div class="time-unit">SS</div>
          </div>
        </div>
        <div id="fade-time-error" class="error" style="display: none;"></div>
      </div>
      <div class="button-container">
        <button class="off-button" id="off-button">Turn Off</button>
        <button class="start-button" id="start-button">Start Fade</button>
      </div>
    `;

    const slider = this.content.querySelector('#brightness-slider');
    const brightnessDisplay = this.content.querySelector('#brightness-value');
    const fadeHours = this.content.querySelector('#fade-hours');
    const fadeMinutes = this.content.querySelector('#fade-minutes');
    const fadeSeconds = this.content.querySelector('#fade-seconds');
    const fadeTimeError = this.content.querySelector('#fade-time-error');
    const startButton = this.content.querySelector('#start-button');
    const offButton = this.content.querySelector('#off-button');

    const getFadeSeconds = () => {
      const h = parseInt(fadeHours.value) || 0;
      const m = parseInt(fadeMinutes.value) || 0;
      const s = parseInt(fadeSeconds.value) || 0;
      return h * 3600 + m * 60 + s;
    };

    const validateFadeTime = () => {
      if (getFadeSeconds() > 14400) {
        fadeTimeError.textContent = 'Fade time must not exceed 4 hours';
        fadeTimeError.style.display = 'block';
        return false;
      }
      fadeTimeError.style.display = 'none';
      return true;
    };

    slider.addEventListener('input', (e) => {
      brightnessDisplay.textContent = e.target.value;
    });

    [fadeHours, fadeMinutes, fadeSeconds].forEach(input => {
      input.addEventListener('input', validateFadeTime);
    });

    startButton.addEventListener('click', () => {
      if (!validateFadeTime()) return;
      this._hass.callService('light', 'turn_on', {
        entity_id: entityId,
        brightness_pct: parseInt(slider.value),
        transition: getFadeSeconds()
      });
    });

    offButton.addEventListener('click', () => {
      if (!validateFadeTime()) return;
      this._hass.callService('light', 'turn_off', {
        entity_id: entityId,
        transition: getFadeSeconds()
      });
    });
  }

  _updateState(stateObj) {
    if (!this.content) return;

    if (!stateObj) {
      this.content.innerHTML = `<div class="error">Entity ${this.config.entity} not found</div>`;
      return;
    }

    const isOn = stateObj.state === 'on';
    const brightness = stateObj.attributes.brightness || 0;
    const brightnessPercent = Math.round((brightness / 255) * 100);

    const badge = this.content.querySelector('#state-badge');
    if (badge) {
      badge.textContent = isOn ? 'ON' : 'OFF';
      badge.className = `state-badge ${isOn ? 'on' : 'off'}`;
    }

    const currentState = this.content.querySelector('#current-state');
    if (currentState) {
      currentState.textContent = `Current: ${isOn ? brightnessPercent + '%' : 'Off'}`;
    }
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
