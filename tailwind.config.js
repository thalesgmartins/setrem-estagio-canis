/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    "./setrem_estagio_canis/templates/**/*.html",
    "./setrem_estagio_canis/static/js/image-cropper.js",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      colors: {
        canvas: 'var(--color-canvas)',
        surface: 'var(--color-surface)',
        elevated: 'var(--color-elevated)',
        subtle: 'var(--color-subtle)',
        ink: {
          primary: 'var(--color-ink-primary)',
          secondary: 'var(--color-ink-secondary)',
          muted: 'var(--color-ink-muted)',
        },
        patas: {
          green: '#05AC78',
          'green-hover': '#049366',
          orange: '#ff9d01',
          blue: '#5e7dfc',
        },
      },
    },
  },
  plugins: [],
};
