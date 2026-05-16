export default defineNuxtConfig({
  devtools: { enabled: true },

  modules: ["@nuxtjs/tailwindcss", "@pinia/nuxt", "@vueuse/nuxt"],

  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE ?? "http://localhost:8000/api/v1",
    },
  },

  typescript: {
    strict: true,
  },

  compatibilityDate: "2025-01-01",
});
