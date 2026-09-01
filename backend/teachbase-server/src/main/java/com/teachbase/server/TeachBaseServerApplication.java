package com.teachbase.server;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.modulith.Modulithic;

@Modulithic
@EnableScheduling
@ConfigurationPropertiesScan
@SpringBootApplication
/**
 * 中文维护说明：本文件属于服务进程装配模块的模块内部实现层，承载本层的稳定数据或行为合同，修改前应检查所有跨模块调用方。
 *
 * 英文术语对照：Java modular-monolith process entry point; business behavior lives in application modules.
 */
public class TeachBaseServerApplication {

    public static void main(String[] args) {
        SpringApplication.run(TeachBaseServerApplication.class, args);
    }
}
