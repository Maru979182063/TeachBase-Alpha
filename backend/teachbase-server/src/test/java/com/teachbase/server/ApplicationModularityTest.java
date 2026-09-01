package com.teachbase.server;

import org.junit.jupiter.api.Test;
import org.springframework.modulith.core.ApplicationModules;

class ApplicationModularityTest {

    @Test
    void moduleDependenciesAreValid() {
        ApplicationModules.of(TeachBaseServerApplication.class).verify();
    }
}
