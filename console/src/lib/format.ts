/**
 * Minor units to the amount a reader recognises, using the currency's own exponent rather
 * than an assumed one — the operator is approving what will actually be charged, so a
 * two-decimal guess is not good enough for a currency that has none.
 */
export function formatAmount(minorUnits: number, currency: string): string {
  const format = new Intl.NumberFormat(undefined, { style: "currency", currency });
  const digits = format.resolvedOptions().maximumFractionDigits ?? 0;
  return format.format(minorUnits / 10 ** digits);
}
