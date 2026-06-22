/** @type {import('tailwindcss').Config} */
// IRIS dark theme: bg #0a0a0f, accent blue #2563EB + cyan #06B6D4.
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        iris: {
          bg: "#0a0a0f",
          accent: "#2563EB",
          cyan: "#06B6D4",
        },
      },
    },
  },
  plugins: [],
};
