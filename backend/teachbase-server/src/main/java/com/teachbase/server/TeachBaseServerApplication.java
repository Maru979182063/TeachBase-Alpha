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
/** Java modular-monolith process entry point; business behavior lives in application modules. */
public class TeachBaseServerApplication {

    public static void main(String[] args) {
        SpringApplication.run(TeachBaseServerApplication.class, args);
    }
}
