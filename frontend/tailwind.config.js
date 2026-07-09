/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0d1117',
        surface: '#161b22',
        border: '#30363d',
        'border-muted': '#21262d',
        text: '#e6edf3',
        muted: '#8b949e',
        accent: '#e94560',
        success: '#3fb950',
        danger: '#ff4444',
        warning: '#ffd700',
        info: '#79c0ff',
        severity: {
          critical: '#ff4444',
          high: '#ff8c00',
          medium: '#ffd700',
          low: '#00cc88',
        },
      },
    },
  },
  plugins: [],
}
