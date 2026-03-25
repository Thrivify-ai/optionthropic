/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#edfffa",
          100: "#cdfaf0",
          400: "#52e6c4",
          500: "#21d1a5",
          600: "#12b48b",
          700: "#0b8e6d",
          900: "#07392d",
        },
        surface: {
          DEFAULT: "var(--color-surface)",
          card:    "var(--color-surface-card)",
          border:  "var(--color-surface-border)",
        },
      },
      fontFamily: {
        sans: ["Manrope", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
};
