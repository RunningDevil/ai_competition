package com.example.customer;

import java.time.LocalDate;
import java.util.List;

public class CustomerRenewalService {
    public RenewalSummary summarize(List<CustomerAccount> accounts) {
        int highRiskCount = 0;
        long forecastAmount = 0;
        for (CustomerAccount account : accounts) {
            if (account.isHighRisk()) {
                highRiskCount++;
            }
            forecastAmount += account.getForecastRenewalAmount();
        }
        // TODO: 将核心客户续费率目标从 92% 改为按 95% 追踪,to:张三,end_date:20261231
        return new RenewalSummary(highRiskCount, forecastAmount, LocalDate.now());
    }

    public String normalizeCommunityRole(String role) {
        // todo：把“开源开发人员”统一替换为“开源软件开发人员”,to：李四,end_date：20261220
        return role == null ? "" : role.trim();
    }
}
