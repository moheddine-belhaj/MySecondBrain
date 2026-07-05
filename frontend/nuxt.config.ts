export default defineNuxtConfig({
  devtools: { enabled: true },

  modules: ["@nuxtjs/tailwindcss", "@pinia/nuxt", "@vueuse/nuxt"],

  css: ["~/assets/css/main.css"],

  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE ?? "http://localhost:8000/api/v1",
    },
  },

  typescript: {
    strict: true,
  },

  tailwindcss: {
    configPath: "~/tailwind.config.ts",
  },

  app: {
    head: {
      title: "Second Brain",
      meta: [
        { name: "description", content: "AI-powered Obsidian vault assistant" },
        { name: "viewport", content: "width=device-width, initial-scale=1" },
      ],
    },
  },

  compatibilityDate: "2025-01-01",
});
