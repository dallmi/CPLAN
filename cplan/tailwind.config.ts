import type { Config } from "tailwindcss";

export default {
  darkMode: ["class"],
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Corporate color palette
        primary: {
          DEFAULT: "#E60000", // Red
          50: "#FFF1F1",
          100: "#FFE0E0",
          200: "#FFC7C7",
          300: "#FF9999",
          400: "#FF5252",
          500: "#E60000",
          600: "#BD000C",
          700: "#8A000A",
          800: "#620004",
          900: "#620004",
        },
        secondary: {
          DEFAULT: "#000000", // Black
          50: "#ECEBE4",
          100: "#CCCABC",
          200: "#CCCABC",
          300: "#B8B3A2",
          400: "#7A7870",
          500: "#7A7870",
          600: "#5A5D5C",
          700: "#404040",
          800: "#404040",
          900: "#000000",
        },
        neutral: {
          DEFAULT: "#FFFFFF", // White
          50: "#FFFFFF",
          100: "#F5F0E1",
          200: "#ECEBE4",
          300: "#CCCABC",
          400: "#CCCABC",
          500: "#B8B3A2",
          600: "#7A7870",
          700: "#7A7870",
          800: "#5A5D5C",
          900: "#404040",
        },
        success: {
          DEFAULT: "#6F7A1A",
          50: "#F0F2E6",
          500: "#6F7A1A",
          700: "#6F7A1A",
        },
        warning: {
          DEFAULT: "#E4A911",
          50: "#FDF6E3",
          500: "#E4A911",
          700: "#E4A911",
        },
        error: {
          DEFAULT: "#BD000C",
          50: "#FFEBE6",
          500: "#BD000C",
          700: "#8A000A",
        },
        info: {
          DEFAULT: "#0C7EC6",
          50: "#ECEBE4",
          500: "#0C7EC6",
          700: "#07476F",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      animation: {
        "fade-in": "fadeIn 0.5s ease-in-out",
        "slide-in": "slideIn 0.3s ease-out",
        "scale-in": "scaleIn 0.2s ease-out",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideIn: {
          "0%": { transform: "translateY(-10px)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" },
        },
        scaleIn: {
          "0%": { transform: "scale(0.95)", opacity: "0" },
          "100%": { transform: "scale(1)", opacity: "1" },
        },
      },
      boxShadow: {
        soft: "0 2px 4px rgba(0,0,0,0.05)",
        medium: "0 4px 6px rgba(0,0,0,0.07)",
        large: "0 10px 15px rgba(0,0,0,0.1)",
        xl: "0 20px 25px rgba(0,0,0,0.1)",
      },
    },
  },
  plugins: [],
} satisfies Config;