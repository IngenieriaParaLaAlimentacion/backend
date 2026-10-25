import { chromium } from "playwright";
import fs from "node:fs/promises";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "../..");
const output = path.join(root, ".context/manual/screenshots");
const fixture = JSON.parse(await fs.readFile(path.join(root, ".context/manual/fixture.json")));
const base = process.env.BACKOFFICE_URL || "http://localhost:3001";
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: "es-AR", timezoneId: "America/Argentina/Buenos_Aires", deviceScaleFactor: 1 });
const extraOnly = process.argv.includes("--extra-only");
let entries;
try {
  entries = JSON.parse(await fs.readFile(path.join(output, "web-captures.json")));
} catch (error) {
  if (error.code !== "ENOENT") throw error;
  entries = [];
}
const failures = [];
page.setDefaultTimeout(15000);
page.setDefaultNavigationTimeout(30000);
await fs.mkdir(output, { recursive: true });
page.on("dialog", d => d.dismiss());

async function shot(id, expected) {
  if (expected) await page.getByText(expected, { exact: false }).first().waitFor();
  await page.locator('[aria-busy="true"]').waitFor({state: "hidden"}).catch(() => {});
  await page.evaluate(() => document.fonts.ready);
  await page.addStyleTag({ content: "nextjs-portal { display: none !important; } *, *::before, *::after { animation-duration: 0s !important; transition-duration: 0s !important; }" });
  await page.screenshot({ path: path.join(output, `${id}.png`), fullPage: true });
  const text = await page.locator("body").innerText();
  await fs.writeFile(path.join(output, `${id}.txt`), text);
  entries = entries.filter(entry => entry.id !== id);
  entries.push({ id, surface: "backoffice", url: page.url(), file: `${id}.png`, expected, capturedAt: new Date().toISOString() });
  await fs.writeFile(path.join(output, "web-captures.json"), JSON.stringify(entries, null, 2));
  console.log(id);
}

async function goto(url, expected) {
  await page.goto(base + url);
  await page.waitForLoadState("networkidle");
  if (expected) await page.getByText(expected, { exact: false }).first().waitFor();
}

try {
  await goto("/signin", "Iniciar sesión");
  await shot("web-acceso", "Iniciar sesión");
  await page.getByRole("textbox", { name: /Email/ }).fill(fixture.accounts.superadmin.email);
  await page.locator('input[type="password"]').fill(fixture.accounts.superadmin.password);
  await page.getByRole("button", { name: "Iniciar sesión", exact: true }).click();
  await page.waitForURL("**/dashboard");
  await page.waitForLoadState("networkidle");
  await shot("web-inicio", "Accesos disponibles");
  const eid = fixture.establishment;
  const routes = [
    ["web-establecimientos", "/dashboard/establishments", "Establecimientos registrados"],
    ["web-establecimiento-alta", "/dashboard/establishments/create", "Nombre"],
    ["web-comedor", `/dashboard/establishments/${eid}`, "Sujetos que asisten"],
    ["web-comedor-relevadores", `/dashboard/establishments/${eid}/field-workers`, "Relevadores"],
    ["web-comedor-perfil", `/dashboard/establishments/${eid}/profile`, "Perfil"],
    ["web-comedor-perfil-editar", `/dashboard/establishments/${eid}/profile?edit=1`, "Guardar perfil"],
    ["web-sujetos", "/dashboard/subjects", "Sujetos registrados"],
    ["web-mediciones", "/dashboard/anthropometric-measurements", "Mediciones antropométricas"],
    ["web-encuestas", "/dashboard/surveys", "Relevamientos FIES"],
    ["web-encuesta-nueva", "/dashboard/surveys/new", "Nueva encuesta"],
    ["web-encuesta-editar", `/dashboard/surveys/${fixture.surveys.subject}`, "Editar encuesta"],
    ["web-encuesta-respuestas", `/dashboard/surveys/${fixture.surveys.subject}/responses`, "Respuestas"],
    ["web-fies-respuestas", `/dashboard/surveys/${fixture.surveys.fies}/responses`, "Respuestas"],
    ["web-stock", `/dashboard/establishments/${eid}/stock`, "Stock"],
    ["web-movimientos", `/dashboard/establishments/${eid}/stock/movements`, "Movimientos"],
    ["web-solicitudes-registro", "/dashboard/requests", "Solicitudes de usuario"],
    ["web-solicitudes-acceso", "/dashboard/requests/establishments", "Solicitudes de establecimiento"],
    ["web-solicitudes-alta", "/dashboard/requests/establishment-creations", "Solicitudes"],
    ["web-usuarios", "/dashboard/users", "Usuarios"],
    ["web-perfil", "/dashboard/profile", "Mi información personal"],
    ["web-perfil-editar", "/dashboard/profile/edit", "Editar perfil"],
  ];
  for (const [id, route, text] of extraOnly ? [] : routes) {
    try {
      await goto(route, text);
      await shot(id, text);
    } catch (error) {
      failures.push(id);
      await fs.writeFile(path.join(output, `${id}-error.txt`), String(error) + "\n" + await page.locator("body").innerText());
      console.error(`FAILED ${id}: ${error.message}`);
    }
  }
  const flows = [
    ["web-encuesta-acciones", async () => {
      await goto("/dashboard/surveys", "Relevamientos FIES");
      await page.getByRole("row").filter({hasText: "Seguimiento alimentario"})
        .getByRole("button", {name: "Más acciones", exact: true}).click();
      await shot("web-encuesta-acciones", "Duplicar");
    }],
    ["web-encuesta-exportar", async () => {
      await goto(`/dashboard/surveys/${fixture.surveys.subject}/responses`, "Respuestas");
      await page.locator('input[type="date"]').first().fill(new Date().toISOString().slice(0, 7) + "-01");
      await page.waitForLoadState("networkidle");
      await shot("web-encuesta-exportar", "Exportar");
      const downloaded = page.waitForEvent("download");
      await page.getByRole("button", {name: "Exportar", exact: true}).click();
      const file = await downloaded;
      await file.saveAs(path.join(root, ".context/manual/downloads", file.suggestedFilename()));
      console.log(`VERIFIED XLSX: ${file.suggestedFilename()}`);
    }],
    ["web-comedor-solicitud-revisar", async () => {
      await goto("/dashboard/requests/establishment-creations", "Solicitudes");
      await page.getByRole("button", {name: "Revisar", exact: true}).first().click();
      await shot("web-comedor-solicitud-revisar", "Aprobar");
    }],
    ["web-solicitud-revisar", async () => {
      await goto("/dashboard/requests", "Solicitudes de usuario");
      await page.getByRole("button", {name: "Revisar", exact: true}).first().click();
      await shot("web-solicitud-revisar", "Aceptar solicitud");
    }],
    ["web-encuesta-respuesta-detalle", async () => {
      await goto(`/dashboard/surveys/${fixture.surveys.subject}/responses`, "Respuestas");
      await page.getByRole("row").filter({hasText: fixture.subject_names[0]}).first().click();
      await shot("web-encuesta-respuesta-detalle", "Detalle de respuesta");
    }],
    ["web-sujeto-detalle", async () => {
      await goto("/dashboard/subjects", "Sujetos registrados");
      await page.getByText(fixture.subject_names[1], {exact: true}).first().click();
      await shot("web-sujeto-detalle", "Documento de identidad");
    }],
    ["web-evolucion", async () => {
      await goto("/dashboard/anthropometric-measurements", "Mediciones antropométricas");
      await page.getByRole("row").filter({hasText: fixture.subject_names[1]}).first().click();
      await page.getByText("Evolución de peso y talla", {exact: true}).waitFor();
      await shot("web-evolucion", "Evolución de peso y talla");
    }],
    ["web-fies-crear", async () => {
      await goto("/dashboard/surveys/new?from=fies", "Nueva encuesta");
      await shot("web-fies-crear", "8/30");
    }],
    ["web-movimiento-registrar", async () => {
      await goto(`/dashboard/establishments/${eid}/stock`, "Stock");
      await page.getByRole("button", {name: "Registrar movimiento", exact: true}).click();
      await shot("web-movimiento-registrar", "Guardar");
    }],
    ["web-usuario-invitar", async () => {
      await goto("/dashboard/users", "Usuarios aceptados");
      await page.getByRole("button", {name: "Invitar analista", exact: true}).click();
      await shot("web-usuario-invitar", "Enviar invitación");
    }],
  ];
  for (const [id, run] of flows) {
    if (extraOnly && !["web-encuesta-acciones", "web-encuesta-exportar"].includes(id)) continue;
    try { await run(); }
    catch (error) {
      failures.push(id);
      await fs.writeFile(path.join(output, `${id}-error.txt`), String(error) + "\n" + await page.locator("body").innerText());
      console.error(`FAILED ${id}: ${error.message}`);
    }
  }
  // Real CSV download, including the new measurement submitted by Android.
  await goto("/dashboard/anthropometric-measurements", "Mediciones antropométricas");
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", {name: /Exportar/}).click();
  const download = await downloadEvent;
  await fs.mkdir(path.join(root, ".context/manual/downloads"), {recursive: true});
  await download.saveAs(path.join(root, ".context/manual/downloads", download.suggestedFilename()));
  console.log(`VERIFIED CSV: ${download.suggestedFilename()}`);
  await page.evaluate(() => localStorage.clear());
  await goto("/forgot-password", "Email");
  await shot("web-recuperar", "Email");
  if (failures.length) throw new Error(`Capture failures: ${failures.join(", ")}`);
} catch (error) {
  await page.screenshot({ path: path.join(output, "debug-web.png"), fullPage: true });
  await fs.writeFile(path.join(output, "debug-web.txt"), await page.locator("body").innerText());
  throw error;
} finally {
  await browser.close();
}
