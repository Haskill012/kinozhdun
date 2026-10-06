const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../website/static/site.js'), 'utf8');

function setup(reducedMotion = false) {
  const timers = new Map();
  let timerId = 0;
  const element = (dataset = {}) => ({
    dataset, attributes: {}, handlers: {}, classes: new Set(),
    addEventListener(name, handler) { this.handlers[name] = handler; },
    setAttribute(name, value) { this.attributes[name] = value; },
    getAttribute(name) { return this.attributes[name]; },
    hasAttribute(name) { return this.attributes[name] !== undefined; },
    removeAttribute(name) { delete this.attributes[name]; if (name === 'data-src') delete this.dataset.src; },
    closest() { return this; }
  });
  const slides = Array.from({ length: 6 }, (_, i) => {
    const slide = element();
    slide.hidden = i !== 0;
    slide.inert = i !== 0;
    slide.attributes['aria-label'] = `Project ${i}`;
    slide.image = element(i ? { src: `image${i}` } : {});
    slide.image.complete = true;
    slide.querySelector = selector => selector === 'img[data-src]' ? (slide.image.dataset.src ? slide.image : null) : slide.image;
    slide.classList = { add: value => slide.classes.add(value), remove: value => slide.classes.delete(value) };
    return slide;
  });
  const dots = slides.map((_, i) => element({ go: String(i) }));
  const controls = element();
  const pause = element();
  const next = element({ direction: '1' });
  next.attributes['data-direction'] = '1';
  dots.forEach(dot => { dot.attributes['data-go'] = dot.dataset.go; });
  const counter = element(), announcement = element(), hero = element();
  hero.querySelectorAll = selector => selector === '[data-slide]' ? slides : dots;
  hero.querySelector = selector => ({ '.spotlight-controls': controls, '.spotlight-pause': pause,
    '.spotlight-counter': counter, '.spotlight-announcement': announcement })[selector];
  hero.contains = target => target === pause || target === next;
  controls.contains = hero.contains;
  controls.querySelector = () => next;
  const reduced = { matches: reducedMotion, addEventListener() {} };
  const document = { hidden: false, activeElement: null, handlers: {}, body: { dataset: {} },
    querySelectorAll: selector => selector === '.dynamic-spotlight' ? [hero] : [],
    querySelector: () => null, addEventListener(name, handler) { this.handlers[name] = handler; } };
  vm.runInNewContext(source, { document, window: { matchMedia: () => reduced },
    setTimeout: (callback, delay) => { const id = ++timerId; timers.set(id, { callback, delay }); return id; },
    clearTimeout: id => timers.delete(id) });
  const click = button => controls.handlers.click({ target: button });
  const fire = delay => {
    const entry = [...timers.entries()].find(([, timer]) => timer.delay === delay);
    assert.ok(entry, `Expected ${delay}ms timer`);
    timers.delete(entry[0]); entry[1].callback();
  };
  const auto = () => [...timers.values()].some(timer => timer.delay === 7000);
  return { slides, dots, controls, pause, next, hero, document, counter, announcement, click, fire, auto };
}

const carousel = setup();
assert.equal(carousel.controls.hidden, false);
assert.equal(carousel.slides.filter(slide => slide.image.dataset.src).length, 4);
assert.ok(carousel.auto());
carousel.fire(7000);
assert.equal(carousel.counter.textContent, '2 / 6');
assert.equal(carousel.slides[0].inert, true);
assert.equal(carousel.slides[1].inert, false);
assert.equal(carousel.announcement.textContent, undefined); // No automatic screen-reader announcements.
carousel.fire(650);
assert.equal(carousel.slides.filter(slide => !slide.hidden).length, 1);
carousel.click(carousel.dots[5]);
assert.equal(carousel.announcement.textContent, 'Project 5');
carousel.click(carousel.next); // Rapid navigation cancels an older fade.
carousel.fire(650);
carousel.fire(650);
assert.equal(carousel.counter.textContent, '1 / 6');
assert.equal(carousel.slides.filter(slide => !slide.hidden).length, 1);
carousel.hero.handlers.focusin();
assert.equal(carousel.auto(), false);
carousel.hero.handlers.focusout();
carousel.fire(0);
assert.ok(carousel.auto());
carousel.document.hidden = true;
carousel.document.handlers.visibilitychange();
assert.equal(carousel.auto(), false);
carousel.document.hidden = false;
carousel.document.handlers.visibilitychange();
carousel.click(carousel.pause);
assert.equal(carousel.auto(), false);

const reduced = setup(true);
assert.equal(reduced.auto(), false);
assert.equal(reduced.pause.disabled, true);
reduced.click(reduced.next);
reduced.fire(0);
assert.equal(reduced.counter.textContent, '2 / 6');
assert.equal(reduced.slides.filter(slide => !slide.hidden).length, 1);
console.log('Carousel timing, pause, reduced motion, image hydration and rapid navigation checks passed');
