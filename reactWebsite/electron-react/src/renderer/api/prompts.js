/** Ready-made requests the panels hand to the AI Strategy Research panel. */

export function improveStrategyPrompt({ strategy, dataFile, reportFile, pnl }) {
  const result =
    reportFile !== undefined && reportFile !== null
      ? ` Its latest run on ${dataFile} is saved as run report ${reportFile}${
          pnl !== undefined && pnl !== null
            ? ` (P&L $${Number(pnl).toFixed(2)})`
            : ''
        }.`
      : '';
  return (
    `Improve my strategy ${strategy}.${result} Read the strategy` +
    `${reportFile ? ' and the report' : ''}, diagnose what is costing money or limiting it, ` +
    `write an improved version as a new file, backtest it${dataFile ? ` on ${dataFile}` : ''} ` +
    `and compare it with the original.`
  );
}

export function analyzeDataPrompt(dataFile) {
  return (
    `Profile ${dataFile} and suggest strategy hypotheses worth backtesting ` +
    `(spreads, order-book imbalance, large moves).`
  );
}
