import QRCode from "qrcode";

export function verificationPath(productId: string) {
  return `/verify/${encodeURIComponent(productId)}`;
}

export function verificationUrl(
  productId: string,
  origin = window.location.origin,
) {
  return new URL(verificationPath(productId), origin).href;
}

function xml(value: string) {
  return value.replace(
    /[<>&"']/g,
    (char) =>
      ({
        "<": "&lt;",
        ">": "&gt;",
        "&": "&amp;",
        '"': "&quot;",
        "'": "&apos;",
      })[char]!,
  );
}

export async function verificationLabel(
  productId: string,
  url: string,
  environment: string,
) {
  const qr = await QRCode.toString(url, {
    type: "svg",
    errorCorrectionLevel: "M",
    margin: 4,
  });
  return `<svg xmlns="http://www.w3.org/2000/svg" width="368" height="480" viewBox="0 0 368 480"><rect width="368" height="480" fill="white"/><g fill="black" font-family="sans-serif" text-anchor="middle"><text x="184" y="30" font-size="22">Veritras</text><text x="184" y="52" font-size="12">${xml(environment)}</text></g>${qr.replace("<svg ", '<svg x="24" y="66" width="320" height="320" ')}<g fill="black" font-family="sans-serif" text-anchor="middle"><text x="184" y="407" font-size="12" textLength="320" lengthAdjust="spacingAndGlyphs">${xml(productId)}</text><text x="184" y="433" font-size="13">Scan to inspect registration evidence</text><text x="184" y="455" font-size="11">Does not authenticate a physical item</text></g></svg>`;
}
