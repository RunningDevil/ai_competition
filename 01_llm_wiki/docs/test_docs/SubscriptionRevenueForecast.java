import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.LinkedHashMap;
import java.util.Map;

public class SubscriptionRevenueForecast {
    static class Cohort {
        final int accounts;
        final BigDecimal arpa;
        final BigDecimal churn;
        final BigDecimal expansion;

        Cohort(int accounts, String arpa, String churn, String expansion) {
            this.accounts = accounts;
            this.arpa = new BigDecimal(arpa);
            this.churn = new BigDecimal(churn);
            this.expansion = new BigDecimal(expansion);
        }
    }

    static BigDecimal forecastMonth(Cohort cohort, int monthIndex) {
        BigDecimal activeAccounts = BigDecimal.valueOf(cohort.accounts);
        BigDecimal monthlyArpa = cohort.arpa;
        for (int i = 0; i < monthIndex; i++) {
            activeAccounts = activeAccounts.multiply(BigDecimal.ONE.subtract(cohort.churn));
            monthlyArpa = monthlyArpa.multiply(BigDecimal.ONE.add(cohort.expansion));
        }
        return activeAccounts.multiply(monthlyArpa).setScale(2, RoundingMode.HALF_UP);
    }

    public static void main(String[] args) {
        Map<String, Cohort> cohorts = new LinkedHashMap<>();
        cohorts.put("SMB", new Cohort(42, "880.00", "0.025", "0.010"));
        cohorts.put("ENT", new Cohort(9, "7600.00", "0.010", "0.018"));
        cohorts.put("PARTNER", new Cohort(16, "2400.00", "0.015", "0.012"));

        for (int month = 0; month < 4; month++) {
            BigDecimal total = BigDecimal.ZERO;
            for (Cohort cohort : cohorts.values()) {
                total = total.add(forecastMonth(cohort, month));
            }
            System.out.println("M" + (month + 1) + "|" + total.setScale(2, RoundingMode.HALF_UP));
        }
    }
}
