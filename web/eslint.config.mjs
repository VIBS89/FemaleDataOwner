import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// eslint-config-next 16 ya publica configuración plana: no hace falta FlatCompat.
const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // Reglas del compilador de React que llegaron con eslint-config-next 16. El código actual carga datos con
    // setState dentro de useEffect en 12 sitios y usa Math.random en el sidebar de shadcn. Se apagan hasta
    // refactorizar: docs/wiki/deuda-tecnica.md.
    rules: {
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/purity": "off",
    },
  },
  globalIgnores(["node_modules/**", ".next/**", "out/**", "build/**", "next-env.d.ts"]),
]);

export default eslintConfig;
